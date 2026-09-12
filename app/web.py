from pathlib import Path

from fastapi.templating import Jinja2Templates


TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIRECTORY))

