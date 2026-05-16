from core.startup import initialise_system
from cli.interface import start_cli

# Boot the system
vector_db_client = initialise_system()

# Terminal UI — for the graphical app run: python -m ui.desktop
start_cli()
