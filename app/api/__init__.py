"""
API blueprint for AttenDANCE system REST API
"""

from flask import Blueprint

bp = Blueprint('api', __name__)

from app.api import routes 