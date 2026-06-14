import sys
from state_machine import JarvisMachine
from logger import setup_logger

# Suppress COM errors that occur when using pycaw to control volume on Windows. These errors are harmless but are hella distracting
# def _suppress_com_errors(unraisable):
#     if 'COM method call without VTable' in str(unraisable.exc_value):
#         return
#     sys.__unraisablehook__(unraisable)

# sys.unraisablehook = _suppress_com_errors




def main():
    setup_logger()
    JarvisMachine()

if __name__ == "__main__":
    main()