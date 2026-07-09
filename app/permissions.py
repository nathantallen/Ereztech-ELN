from functools import wraps

from flask import abort, g
from flask_login import current_user


def current_role():
    """The Role row for the signed-in user, cached per request."""
    if not current_user.is_authenticated:
        return None
    if not hasattr(g, "_role_obj"):
        from .models import Role

        g._role_obj = Role.query.filter_by(name=current_user.role).first()
    return g._role_obj


def is_admin():
    role = current_role()
    return bool(role and role.manage_users)


def can_edit_production():
    role = current_role()
    return bool(role and (role.edit_production or role.manage_users))


def can_edit_rd(project=None):
    role = current_role()
    if not role:
        return False
    if role.manage_users or role.edit_rd_all:
        return True
    if role.edit_rd_own:
        return project is None or project.researcher_id == current_user.id
    return False


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_admin():
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def production_editor_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not can_edit_production():
            abort(403)
        return fn(*args, **kwargs)

    return wrapper
