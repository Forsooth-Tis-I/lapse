from lapse.exec.recipes.canva_change_email import RECIPE as CANVA_CHANGE_EMAIL
from lapse.exec.recipes.notion_change_email import RECIPE as NOTION_CHANGE_EMAIL
from lapse.exec.recipes.x_change_phone import RECIPE as X_CHANGE_PHONE

RECIPES = {recipe.name: recipe for recipe in (NOTION_CHANGE_EMAIL, CANVA_CHANGE_EMAIL, X_CHANGE_PHONE)}
