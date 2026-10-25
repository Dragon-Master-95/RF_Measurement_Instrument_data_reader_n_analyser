# This file is the main file to run the GUI for the measurement
# analysis. It will import rf_toolkit/Measurement_analysis_GUI.py
# and run the GUI.
#
# Usage:
#   python main.py                      # open the GUI
#   python main.py file1.s2p file2.s2p  # open the GUI with files already loaded

import sys

from rf_toolkit.Measurement_analysis_GUI import run

if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
