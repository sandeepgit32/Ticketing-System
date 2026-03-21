# Database Service

This service provides the MySQL database for BookEventTicket with automatic schema initialization.

## Overview

The database service is a MySQL 8.0 container that automatically runs initialization scripts on first startup. All database schema definitions are centralized here to ensure consistency across the application.

## Structure

- `init.sql` - SQL script that creates all required tables and indexes
- `Dockerfile` - Builds the database image with initialization scripts
- `README.md` - This file

## Tables

### users
Authentication and user information table.

### events
Event catalog with venue and timing information.

### seats
Normalized seat inventory per event, including occupancy and per-seat pricing.

### reservations
Temporary seat reservations with expiration tracking.

### bookings
Confirmed bookings with payment status.

## Usage

The database service is configured in `docker-compose.yml` and automatically initializes on first run. All application services connect to this database using the hostname `database`.

## Environment Variables

- `MYSQL_ROOT_PASSWORD` - Root user password
- `MYSQL_DATABASE` - Database name to create
- `MYSQL_USER` - Application user to create
- `MYSQL_PASSWORD` - Application user password

## Initialization

The `init.sql` script is automatically executed when the container is first created. Subsequent restarts will not re-run the script. To reinitialize:

1. Stop and remove the container: `docker-compose down`
2. Remove the volume: `docker volume rm ticketing-system_mysql_data`
3. Restart: `docker-compose up database`
