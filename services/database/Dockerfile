FROM mysql:8.0

# Copy initialization scripts
COPY init.sql /docker-entrypoint-initdb.d/

# The scripts in /docker-entrypoint-initdb.d/ will be automatically
# executed when the container starts for the first time
