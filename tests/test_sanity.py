from supplier_check import __version__


def test_package_version() -> None:
    """Sanity test verifying package version is defined."""
    assert __version__ == "0.1.0"
