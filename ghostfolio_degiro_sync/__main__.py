"""Transitional module command; preserve the existing command's exit contract."""

import runpy

runpy.run_module("degiro_to_ghostfolio", run_name="__main__")
