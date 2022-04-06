from conda.base.context import context
from mamba import repoquery as repoquery_api
import libmambapy as api
import argparse
import json
import requests
import logging
import hashlib
import pathlib
import fnmatch
import bz2
import os

context.dry_run=True
context.json=True
context.download_only=True

REPODATA_FILENAME="repodata.json"
REPODATA_FILENAME_COMPRESSED="repodata.json.bz2"
VALIDATE_SHA256=True

global repo_dir

global session
session = requests.Session()

global packages_resolved
packages_resolved = {}

global packages_local
packages_local = {
    'noarch': {},
    'linux-64': {}
}


def arg_parser():
    arg = argparse.ArgumentParser(
        prog='repo.sh',
        description="""
        Makes a partial copy of a conda channel in a local directory.
        """
    )
    arg.add_argument(
        "action",
        choices=['clone','validate','list', 'check', 'clean'],
        help=("""
            An 'clone' action downloads all missing packages
            and new versions of existing packages.
            Any already downloaded ones will not be removed.
            A 'validate' check integrity and consistency of existing repo dir.
            A 'list' only list current package in repo with hashes and versions.
            A 'check' run 'clone' in dry_run mode
            A 'clean' remove invalid packages from target_dir
        """
        )
    )
    arg.add_argument(
        "--packages-list",
        default=os.path.dirname(os.path.realpath(__file__)) + "/../package.list",
        help=(
            "Filepath with packages list to clone (one package per line"
        ),
    )
    arg.add_argument(
        "--upstream-channel",
        default="conda-forge",
        help=(
            "The target channel to mirror. Can be a channel on anaconda.org "
            'like "conda-forge" or a full qualified channel like '
            '"https://repo-cz.cz.prod/custom_repos/conda-forge"'
        ),
    )
    arg.add_argument(
        "--target-directory",
        required=True,
        help="The place where packages should be mirrored to",
    )
    return arg.parse_args()


def init_logger(verbosity: int) -> None:
    global logger
    logger = logging.getLogger("conda-forge-tools")
    logmap = {0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG}
    loglevel = logmap.get(min(int(verbosity), 3))
    for handler in logger.handlers:
        logger.removeHandler(handler)
    logger.setLevel(loglevel)
    format_string = "%(levelname)s: %(message)s"
    formatter = logging.Formatter(fmt=format_string)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(loglevel)
    stream_handler.setFormatter(fmt=formatter)
    logger.addHandler(stream_handler)



def init_pool(channels=["conda-forge"], platform="linux-64", use_installed=False):
    global pool
    logger.info("Downloading repo metadata from {}".format(channels))
    pool = repoquery_api.create_pool(channels, platform, use_installed)


def solve_package(package, pool, packages={}, exclude_pinned=True, pinned_packages=["python=3.6"]):
    if isinstance(package, list):
        pkgs = package
    else:
        pkgs = [package]
    solver_options = [(api.SOLVER_FLAG_STRICT_REPO_PRIORITY, 1)]
    solver = api.Solver(pool, solver_options)
    if exclude_pinned:
        for pinned in pinned_packages:
            solver.add_pin(pinned)
    else:
        pkgs = pkgs + pinned_packages
    solver.add_jobs(pkgs, api.SOLVER_INSTALL)
    solver.solve()
    solver.is_solved()
    package_cache = api.MultiPackageCache(["/tmp/conda"])
    transaction = api.Transaction(solver, package_cache)
    mmb_specs, to_link, to_unlink = transaction.to_conda()
    # will clear solver instance
    err = solver.all_problems_to_str()
    if err != "":
        raise ValueError("Can't resolve dependencies for package %s with error: %s", package, err)
    for link in to_link:
        js = json.loads(link[2])
        platform = js['subdir']
        name = js['fn']
        if not packages.get(platform):
            packages[platform] = {}
        if not packages[platform].get(name):
            packages[platform][name] = js
    return packages


def analyze_local_packages(target_repo, platform, remove=False):
    result = {
        'unknonw_files': [],
        'invalid_packages': [],
        'packages': {},
        'removed': remove
    }
    contents = []
    local_dir = os.path.join(target_repo, platform)
    if os.path.isdir(local_dir):
        contents = os.listdir(local_dir)
        contents.remove(REPODATA_FILENAME)
        contents.remove(REPODATA_FILENAME_COMPRESSED)
    repodata_file = os.path.join(local_dir, REPODATA_FILENAME)
    if os.path.isfile(repodata_file):
        try:
            current_repodata = json.load(open(repodata_file, "r"))
            current_packages = current_repodata.get('packages', {})
        except Exception:
            logger.warning("Can't decode current repodata in %", repodata_file)
            result["unknonw_files"] = contents
            return result
    for filename in contents:
        pkg = current_packages.get(filename)
        try:
            package_validate(pkg, os.path.join(local_dir, filename))
            result["packages"][filename] = pkg
        except Exception:
            result["invalid_packages"].append(filename)

    if remove:
        for filename in result["unknonw_files"] + result["invalid_packages"]:
            path = os.path.join(local_dir, filename)
            logger.info("Removing '{}' invalid file".format(path))
            os.remove(path)
            result["invalid_packages"] = []
            result["unknonw_files"] = []
    return result


def cleanup_files(files_to_delete):
    for file in files_to_delete:
        if os.path.isfile(file):
            logger.info("Removing file %s", file)
            os.remove(file)


def determine_size(packages, pool):
    count = len(packages)
    i = 0
    failed = []
    for package in packages:
        i += 1
        try:
            solve_package(package, pool, packages_resolved, exclude_pinned=False)
        except:
            failed.append(package)
            pass
    logger.debug(i, "/", count, package)
    result = {}
    for platform in packages_resolved.keys():
        if not result.get(platform):
            result[platform] = {"size": 0, "count": 0}
        for name in packages_resolved[platform]:
            result[platform]['size'] += packages_resolved[platform][name]["size"]
            result[platform]['count'] += 1
    return (failed, result)


def download_and_validate_package(
    pkg,
    target_repo,
    session: requests.Session,
    chunk_size: int = 16 * 1024,
    dry_run = False
):
    downloaded = False
    pathlib.Path(
        target_repo,
        pkg["subdir"]
    ).mkdir(
        parents=True,
        exist_ok=True
    )
    download_filename = os.path.join(
        target_repo,
        pkg["subdir"],
        pkg["fn"]
    )
    if os.path.isfile(download_filename):
        try:
            package_validate(pkg, download_filename)
            #package already downloaded and valid
            return downloaded
        except ValueError:
            os.remove(download_filename)
            pass

    if dry_run:
        return True

    with open(download_filename, "w+b") as file:
        ret = session.get(pkg["url"], stream=True)
        size = int(ret.headers.get("Content-Length", 0))
        for data in ret.iter_content(chunk_size):
            file.write(data)
        file.close()
        downloaded = True
    try:
        package_validate(pkg, download_filename)
    except ValueError as ex:
        os.remove(download_filename)
        raise ex
    logger.info(
        "Downloaded: %s, file_size: %s, sha256: %s",
        pkg["url"],
        pkg["size"],
        pkg["sha256"]
    )
    return downloaded


def package_validate(pkg, filepath):
    file_size = os.path.getsize(filepath)
    if file_size <= 0:
        raise ValueError(
            "File size must be a greater that 0, current size is %s",
            file_size
        )
    if file_size != pkg["size"]:
        raise ValueError(
            "File size mismatch for %s, expected %s but downloaded %s",
            pkg["fn"],
            pkg["size"],
            file_size
        )
    if VALIDATE_SHA256:
        calc = hashlib.sha256(open(filepath, "rb").read()).hexdigest()
        if pkg['sha256'] != calc:
            raise ValueError(
                "Sha256 mismatch for %s, expected %s but downloaded %s",
                pkg["fn"],
                pkg["sha256"],
                calc
            )


def process_package(pkg, target_repo, dry_run=False):
    if dry_run:
        return (True, pkg['size'])
    else:
        try:
            r = download_and_validate_package(pkg, target_repo, session=session)
            return (r, pkg['size'])
        except Exception as ex:
            logger.exception("Unexpected error: %s.", ex)
            return (False, 0)


def merge_repodata(local_packages, new_packages):
    count = 0
    for name in local_packages.keys():
        if not new_packages.get(name):
            new_packages[name] = local_packages[name]
            count += 1
    return count


def write_repodata(platform, target_repo, packages_dict): 
    repodata_dict = {
        "info": {
            "subdir": platform
        },
        "packages": packages_dict
    }
    data = json.dumps(repodata_dict, indent=2, sort_keys=True)
    # strip trailing whitespace
    data = "\n".join(line.rstrip() for line in data.splitlines())
    # make sure we have newline at the end
    if not data.endswith("\n"):
        data += "\n"
    package_dir = os.path.join(target_repo, platform)
    json_path = os.path.join(package_dir, REPODATA_FILENAME)
    with open(json_path, "w") as fo:
        fo.write(data)
        logger.info("Written %s", json_path)
    bz2_path = os.path.join(package_dir, REPODATA_FILENAME_COMPRESSED)
    with open(bz2_path, "wb") as fo:
        fo.write(bz2.compress(data.encode("utf-8")))
        logger.info("Written %s", bz2_path)



def download_packages(dry_run=False):
    result_all = []
    for platform in packages_resolved.keys():
        result = {
            'platform': platform,
            'total_size': 0,
            'new': 0,
            'old': 0,
            'count': 0,
            'failed': 0,
            'failed_packages': []
        }
        for name in packages_resolved[platform].keys(): 
            (r, size) = process_package(packages_resolved[platform][name], repo_dir, dry_run=dry_run)
            if r:
                result['new'] += 1
            if size > 0:
                result['count'] += 1
                result['total_size'] += size
            else:
                result['failed'] += 1
                #result['failed_packages'].append(name)
                to_remove.append(name)
        c = merge_repodata(packages_local[platform], packages_resolved[platform])
        result["old"] = c
        if dry_run == False:
            write_repodata(platform, repo_dir, packages_resolved[platform])
        result_all.append(result)
    return result_all


if __name__ == '__main__':
    args = arg_parser()

    init_logger(2)
    to_remove = []

    repodata = {
        'linux-64': {},
        'noarch': {}
    }

    repo_dir = args.target_directory

    if args.action in ["clone", "check"]:

        os.makedirs(repo_dir, exist_ok=True)
        init_pool(channels=[args.upstream_channel])
        for platform in packages_local.keys():
            result = analyze_local_packages(repo_dir, platform)
            packages_local[platform] = result["packages"]

        file1 = open(args.packages_list, "r").readlines()
        (f, r) = determine_size(file1, pool)
        res = download_packages(dry_run=args.action == "check")
        for platform in res:
            print("{}".format(platform['platform']))
            print("    size: {}".format(platform['total_size']))
            print("    packages: {}".format(platform['count']))
            print("    new packages: {}".format(platform['new']))
            print("    invalid packages: {}".format(platform['failed']))

    if args.action in ["validate", "clean"]:
        for platform in packages_local.keys():
            result = analyze_local_packages(repo_dir, platform, remove=args.action == "clean")
            print("{}".format(platform))
            print("    packages: {}".format(len(result['packages'])))
            print("    unknonw_files: {}".format(result['unknonw_files']))
            print("    invalid_packages: {}".format(result['invalid_packages']))

    if args.action == "list":
        for platform in packages_local.keys():
            result = analyze_local_packages(repo_dir, platform)
            for name in result['packages'].keys():
                pkg = result['packages'][name]
                print("{}: {}={}".format(platform, pkg['name'], pkg['version']))




#  1.  validate current repo (all files match sha256, no files without metadata)
#  2.  load pool metadata (repodata.json from conda-forge)
#  3.  determine dependencies of new packages
#  4.  compare old repodata with new
#  5.  download and validate a new packages
#  6.  move downloaded packages into repo dir
#  7a. remove old packages
#  7b. keep old packages
#  8.  update repodata.json
#  9.  generate changelog document
# 10.  validate new repo

# Utils:
# a) list packages with version, last update and size
# b) determine size by package list
# c) compare repo diff

