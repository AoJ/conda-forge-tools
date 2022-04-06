# Conda forge tools

## Clone

Clone (or update) conda forge repository to local dir. Tested on centos/rhel/oralinux (7,8, Stream).

Require access to internet domains:
- https://conda.anaconda.org/conda-forge
- https://github.com/conda-forge
- https://objects.githubusercontent.com


Used to clone conda-forge (or any other repository) locally. It receives as input a "packages.list" file with a list of packages to be cloned. This file is created manually based on the packages currently in use, and deliberately excludes packages with huge sizes.

Clone is done using the "freeze" method for the current package tree, no cloning of multiple versions into history. It is possible to add any additional versions to the list as <name>=<version> in the same syntax as used when installing conda packages.

For each of the input packages, their dependency tree is traversed and each dependency is downloaded. Any conflicts where one package has a dependency on version X and another on version Y are resolved by downloading both versions. Conflict resolution is left to the installation itself.

Cloning itself is additive, it can be run on top of an already cloned repository and only new packages and their versions are added, so the size of the repository grows and grows. The repository does not include the process and retention and deletion of old packages (can be added in future versions).

The cloning process verifies the hash of each already downloaded package (for a 40GB repo it can take several hours). Similarly, the hash of all downloaded packages is verified against the metadata. For editing/testing and exploring, it is advisable to use a minimal packages.list (there is a packages.list.test with a few small packages in the repository).

The entire package tree depends on python 3.6 and all downloaded packages are python 3.6 compatible. And in the future, it is possible to clone multiple python versions into a single repo, or better yet, have a separate repo for each python version.


### Usage

```
CONDA_HOME=/var/lib/conda/conda ./repo.sh [-h] [--packages-list PACKAGES_LIST] [--upstream-channel UPSTREAM_CHANNEL] --target-directory TARGET_DIRECTORY {clone,validate,list,check,clean}
```


* 1. clone a fresh repository into /tmp/repo

```
CONDA_HOME=/var/lib/conda/conda ./repo.sh --target-directory /tmp/repo clone
```


* 2. update local repository and download a new packages

```
CONDA_HOME=/var/lib/conda/conda ./repo.sh --target-directory /tmp/repo update
```



* 3. check local repository for a new packages

```
CONDA_HOME=/var/lib/conda/conda ./repo.sh --target-directory /tmp/repo check
```


* 4. list packages in local repo

```
CONDA_HOME=/var/lib/conda/conda ./repo.sh --target-directory /tmp/repo list
```



* 5. validate packages in local repo

```
CONDA_HOME=/var/lib/conda/conda ./repo.sh --target-directory /tmp/repo validate
```


For testing you can place a smaller packages list for cloning. Add argument `--packages-list $(pwd)/package.list.test` 

