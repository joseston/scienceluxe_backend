
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Database connection parameters
DB_HOST = "localhost"
DB_USER = "scienceluxe_user"
DB_PASS = "12345"
DB_PORT = "5433"
NEW_DB_NAME = "scienceluxe_1"

def create_database():
    try:
        # Connect to the default 'postgres' database to create the new database
        con = psycopg2.connect(
            dbname="postgres",
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT
        )
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()
        
        # Check if database exists
        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{NEW_DB_NAME}'")
        exists = cur.fetchone()
        
        if not exists:
            print(f"Creating database {NEW_DB_NAME}...")
            cur.execute(f"CREATE DATABASE {NEW_DB_NAME}")
            print(f"Database {NEW_DB_NAME} created successfully.")
        else:
            print(f"Database {NEW_DB_NAME} already exists.")
            
        cur.close()
        con.close()
        
    except Exception as e:
        print(f"Error creating database: {e}")

if __name__ == "__main__":
    create_database()
