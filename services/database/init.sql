-- Initialize all database tables for BookEventTicket

-- Users table (for authentication)
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    user_role ENUM('Admin', 'User') NOT NULL DEFAULT 'User',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email)
);

-- Events table
CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    venue VARCHAR(255),
    start_time TIMESTAMP,
    closed TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seats table (normalized seat inventory per event)
CREATE TABLE IF NOT EXISTS seats (
    event_id VARCHAR(36) NOT NULL,
    seat_id VARCHAR(20) NOT NULL,
    occupied TINYINT(1) NOT NULL DEFAULT 0,
    reservation_id VARCHAR(36) DEFAULT NULL,
    price DECIMAL(10, 2) NOT NULL,
    PRIMARY KEY (event_id, seat_id),
    INDEX idx_seats_event_occupied (event_id, occupied),
    INDEX idx_seats_reservation_id (reservation_id)
);

-- Reservations table (temporary seat holds before payment capture)
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id VARCHAR(36) PRIMARY KEY,
    event_id VARCHAR(36) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL,
    seats JSON NOT NULL,
    expires_at TIMESTAMP NULL,
    confirmed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_reservations_event_id (event_id),
    INDEX idx_reservations_user_email (user_email),
    INDEX idx_reservations_status (status)
);

-- Bookings table (handles both reservations and confirmed bookings via status field)
-- Status values: 'reserved' (temporary hold), 'confirmed' (payment completed), 'expired', 'cancelled'
CREATE TABLE IF NOT EXISTS bookings (
    booking_id VARCHAR(36) PRIMARY KEY,
    reservation_id VARCHAR(36) NULL,
    event_id VARCHAR(36) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL,
    seats JSON NOT NULL,
    payment_status VARCHAR(20) NOT NULL,
    total_amount DECIMAL(10, 2) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    INDEX idx_user_email (user_email),
    INDEX idx_reservation_id (reservation_id),
    INDEX idx_event_id (event_id),
    INDEX idx_status (status)
);

-- Insert sample events
-- INSERT INTO events (event_id, name, venue, start_time) VALUES
--     ('event-001', 'Summer Music Festival 2026', 'Central Park Arena', '2026-07-15 19:00:00'),
--     ('event-002', 'Tech Conference 2026', 'Convention Center Hall A', '2026-08-20 09:00:00'),
--     ('event-003', 'Broadway: The Phantom Returns', 'Grand Theater', '2026-09-10 20:00:00'),
--     ('event-004', 'NBA Finals Game 5', 'Sports Stadium', '2026-06-18 20:30:00'),
--     ('event-005', 'Classical Orchestra Evening', 'Symphony Hall', '2026-10-05 19:30:00'),
--     ('event-006', 'Comedy Night Special', 'Laugh Factory', '2026-08-08 21:00:00'),
--     ('event-007', 'Rock Legends Reunion Tour', 'Metro Arena', '2026-11-12 20:00:00'),
--     ('event-008', 'International Food Festival', 'Waterfront Plaza', '2026-09-25 12:00:00')
-- ON DUPLICATE KEY UPDATE event_id=event_id;
