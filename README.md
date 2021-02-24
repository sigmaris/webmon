The code is all contained within one Python package, so the PostgreSQL client psycopg2
is installed as a requirement of the website checker, even though the website checker
doesn't use the database directly. This could be changed if the checker and the database
recorder were split into two packages - or if psycopg2 was made an optional requirement.
