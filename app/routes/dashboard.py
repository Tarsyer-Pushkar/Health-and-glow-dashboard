from flask import Blueprint, render_template, redirect, url_for, session

dashboard_bp = Blueprint("dashboard", __name__)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

@dashboard_bp.route("/footfall")
@login_required
def footfall():
    return render_template("footfall.html")

