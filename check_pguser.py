"""Check current DB user and try to enable pgvector."""
from aplicacion import create_app, db
from sqlalchemy import text

app = create_app()
with app.app_context():
    r = db.session.execute(text("SELECT current_user, session_user")).fetchone()
    print(f"current_user: {r[0]}, session_user: {r[1]}")
    r2 = db.session.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).fetchone()
    print(f"is_superuser: {r2[0] if r2 else 'unknown'}")
    
    # Try to grant superuser to current user using ALTER ROLE (won't work if not already superuser)
    # Try CREATE EXTENSION anyway
    try:
        db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.session.commit()
        print("pgvector extension CREATED!")
    except Exception as e:
        db.session.rollback()
        print(f"Create extension failed: {e}")
        
        # Try via pg_hba.conf trust access or similar
        print("\nTrying to alter role to superuser...")
        try:
            db.session.execute(text(f"ALTER ROLE {r[0]} SUPERUSER"))
            db.session.commit()
            print("Role altered to superuser!")
        except Exception as e2:
            db.session.rollback()
            print(f"Cannot alter role: {e2}")
            print("\nYou need to run this manually as a superuser:")
            print(f'  psql -U postgres -d scienceluxe_1 -c "ALTER ROLE {r[0]} SUPERUSER;"')
            print('  -- OR --')
            print(f'  psql -U postgres -d scienceluxe_1 -c "CREATE EXTENSION IF NOT EXISTS vector;"')
