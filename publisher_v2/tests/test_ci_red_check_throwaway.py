"""Throwaway CI red-check proof."""


def test_ci_red_check_throwaway() -> None:
    raise AssertionError("intentional failure to verify CI rejects red suites")
