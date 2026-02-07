-- Initialize all database tables for the ticketing system

-- Users table (for authentication)
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bookings table (handles both reservations and confirmed bookings via status field)
-- Status values: 'reserved' (temporary hold), 'confirmed' (payment completed), 'expired', 'cancelled'
CREATE TABLE IF NOT EXISTS bookings (
    booking_id VARCHAR(36) PRIMARY KEY,
    event_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL,
    seats JSON NOT NULL,
    payment_status VARCHAR(20) NOT NULL,
    total_amount DECIMAL(10, 2) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    INDEX idx_user_id (user_id),
    INDEX idx_event_id (event_id),
    INDEX idx_status (status)
);

-- Insert sample events
INSERT INTO events (event_id, name, venue, start_time) VALUES
    ('event-001', 'Summer Music Festival 2026', 'Central Park Arena', '2026-07-15 19:00:00'),
    ('event-002', 'Tech Conference 2026', 'Convention Center Hall A', '2026-08-20 09:00:00'),
    ('event-003', 'Broadway: The Phantom Returns', 'Grand Theater', '2026-09-10 20:00:00'),
    ('event-004', 'NBA Finals Game 5', 'Sports Stadium', '2026-06-18 20:30:00'),
    ('event-005', 'Classical Orchestra Evening', 'Symphony Hall', '2026-10-05 19:30:00'),
    ('event-006', 'Comedy Night Special', 'Laugh Factory', '2026-08-08 21:00:00'),
    ('event-007', 'Rock Legends Reunion Tour', 'Metro Arena', '2026-11-12 20:00:00'),
    ('event-008', 'International Food Festival', 'Waterfront Plaza', '2026-09-25 12:00:00')
ON DUPLICATE KEY UPDATE event_id=event_id;
