"""Allow `python -m backend.chat` and `python -m backend.chat --validate`."""

import sys

if "--validate" in sys.argv:
    from backend.chat.interfaces.validate import validate

    validate()
else:
    from backend.chat.interfaces.cli_chat import main

    main()
