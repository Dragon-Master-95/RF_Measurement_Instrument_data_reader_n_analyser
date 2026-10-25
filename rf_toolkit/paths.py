# Project folders, defined once so modules don't depend on where they sit.
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(PACKAGE_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "Data_files")
