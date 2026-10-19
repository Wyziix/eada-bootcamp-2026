CREATE TABLE `auth_limits` (
	`key` text PRIMARY KEY NOT NULL,
	`hits` integer NOT NULL,
	`window_start` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `conversations` (
	`id` text PRIMARY KEY NOT NULL,
	`listing_id` text NOT NULL,
	`buyer_id` text NOT NULL,
	`seller_id` text NOT NULL,
	`buyer_read_at` integer NOT NULL,
	`seller_read_at` integer NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL,
	FOREIGN KEY (`listing_id`) REFERENCES `listings`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`buyer_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`seller_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `conversation_listing_buyer` ON `conversations` (`listing_id`,`buyer_id`);--> statement-breakpoint
CREATE INDEX `conversation_seller` ON `conversations` (`seller_id`);--> statement-breakpoint
CREATE INDEX `conversation_buyer` ON `conversations` (`buyer_id`);--> statement-breakpoint
CREATE TABLE `listing_photos` (
	`id` text PRIMARY KEY NOT NULL,
	`listing_id` text NOT NULL,
	`content_type` text NOT NULL,
	`data` blob NOT NULL,
	`byte_length` integer NOT NULL,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`listing_id`) REFERENCES `listings`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `listing_photos_listing_id_unique` ON `listing_photos` (`listing_id`);--> statement-breakpoint
CREATE TABLE `listings` (
	`id` text PRIMARY KEY NOT NULL,
	`seller_id` text NOT NULL,
	`title` text NOT NULL,
	`description` text NOT NULL,
	`property_type` text NOT NULL,
	`address` text NOT NULL,
	`city` text NOT NULL,
	`postal_code` text NOT NULL,
	`neighborhood` text NOT NULL,
	`price` integer NOT NULL,
	`bedrooms` integer NOT NULL,
	`bathrooms` real NOT NULL,
	`area_sqft` real NOT NULL,
	`year_built` integer NOT NULL,
	`garage` integer NOT NULL,
	`quality` integer NOT NULL,
	`contact_name` text NOT NULL,
	`contact_email` text NOT NULL,
	`contact_phone` text NOT NULL,
	`status` text NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL,
	FOREIGN KEY (`seller_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `listings_seller` ON `listings` (`seller_id`);--> statement-breakpoint
CREATE INDEX `listings_browse` ON `listings` (`status`,`created_at`);--> statement-breakpoint
CREATE TABLE `messages` (
	`id` text PRIMARY KEY NOT NULL,
	`conversation_id` text NOT NULL,
	`sender_id` text NOT NULL,
	`body` text NOT NULL,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`conversation_id`) REFERENCES `conversations`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`sender_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `messages_conversation` ON `messages` (`conversation_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `sessions` (
	`token_hash` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`expires_at` integer NOT NULL,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `sessions_user` ON `sessions` (`user_id`);--> statement-breakpoint
CREATE INDEX `sessions_expiry` ON `sessions` (`expires_at`);--> statement-breakpoint
CREATE TABLE `users` (
	`id` text PRIMARY KEY NOT NULL,
	`email` text NOT NULL,
	`password_hash` text NOT NULL,
	`name` text NOT NULL,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `users_email_unique` ON `users` (`email`);