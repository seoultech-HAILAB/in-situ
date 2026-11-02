"""Platform-specific worker limits, before loading pandas/numpy."""


def install_posix_limits(platform, resource):
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    # Darwin's address-space limit is unsuitable for modern Python/NumPy
    # mappings. The parent enforces resident memory there instead.
    if platform != 'darwin':
        resource.setrlimit(resource.RLIMIT_AS, (768*1024*1024, 768*1024*1024))
