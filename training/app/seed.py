"""First-run seed: the default administrator login. Runs only when users.json
does not exist. The curriculum (playlist.yaml, quiz.yaml) is copied from
app/content/ by Storage.ensure_layout."""
from werkzeug.security import generate_password_hash


def seed_initial_data(storage):
    initial_password = "ereztech"
    storage.save_users([{
        "username": "admin",
        "full_name": "Administrator",
        "password_hash": generate_password_hash(initial_password),
        "role": "admin",
        "tracks": [],
        "active": True,
    }])
    print("\n*** Ereztech Safety Training default administrator credentials ***")
    print("Username: admin")
    print("Password: %s" % initial_password)
    print("Change this password under My password after signing in.\n", flush=True)
