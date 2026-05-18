#!/usr/bin/env python3
"""Root entry point. Delegates to backend.chat."""

import sys

if "--validate" in sys.argv:
    from backend.chat.interfaces.validate import validate

    validate()
else:
    from backend.chat.interfaces.cli_chat import main

    main()
