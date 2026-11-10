"""Run only the local two-server connection check."""
from cd import main
import sys

if __name__ == '__main__':
    sys.argv = [sys.argv[0], 'smoke']
    sys.exit(main())
