import { sqliteTable, text, integer, real, index, uniqueIndex, blob } from "drizzle-orm/sqlite-core";

export const users = sqliteTable("users", {
  id: text("id").primaryKey(), email: text("email").notNull().unique(),
  passwordHash: text("password_hash").notNull(), name: text("name").notNull(), createdAt: integer("created_at").notNull(),
});
export const sessions = sqliteTable("sessions", {
  tokenHash: text("token_hash").primaryKey(), userId: text("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  expiresAt: integer("expires_at").notNull(), createdAt: integer("created_at").notNull(),
}, t => [index("sessions_user").on(t.userId), index("sessions_expiry").on(t.expiresAt)]);
export const authLimits = sqliteTable("auth_limits", {
  key: text("key").primaryKey(), hits: integer("hits").notNull(), windowStart: integer("window_start").notNull(),
});
export const listings = sqliteTable("listings", {
  id: text("id").primaryKey(), sellerId: text("seller_id").notNull().references(() => users.id),
  title: text("title").notNull(), description: text("description").notNull(), propertyType: text("property_type").notNull(),
  address: text("address").notNull(), city: text("city").notNull(), postalCode: text("postal_code").notNull(), neighborhood: text("neighborhood").notNull(),
  price: integer("price").notNull(), bedrooms: integer("bedrooms").notNull(), bathrooms: real("bathrooms").notNull(),
  areaSqft: real("area_sqft").notNull(), yearBuilt: integer("year_built").notNull(), garage: integer("garage").notNull(), quality: integer("quality").notNull(),
  contactName: text("contact_name").notNull(), contactEmail: text("contact_email").notNull(), contactPhone: text("contact_phone").notNull(),
  status: text("status").notNull(), createdAt: integer("created_at").notNull(), updatedAt: integer("updated_at").notNull(),
}, t => [index("listings_seller").on(t.sellerId), index("listings_browse").on(t.status, t.createdAt)]);
export const listingPhotos = sqliteTable("listing_photos", {
  id: text("id").primaryKey(), listingId: text("listing_id").notNull().unique().references(() => listings.id, { onDelete: "cascade" }),
  contentType: text("content_type").notNull(), data: blob("data", { mode: "buffer" }).notNull(),
  byteLength: integer("byte_length").notNull(), createdAt: integer("created_at").notNull(),
});
export const conversations = sqliteTable("conversations", {
  id: text("id").primaryKey(), listingId: text("listing_id").notNull().references(() => listings.id),
  buyerId: text("buyer_id").notNull().references(() => users.id), sellerId: text("seller_id").notNull().references(() => users.id),
  buyerReadAt: integer("buyer_read_at").notNull(), sellerReadAt: integer("seller_read_at").notNull(),
  createdAt: integer("created_at").notNull(), updatedAt: integer("updated_at").notNull(),
}, t => [uniqueIndex("conversation_listing_buyer").on(t.listingId, t.buyerId), index("conversation_seller").on(t.sellerId), index("conversation_buyer").on(t.buyerId)]);
export const messages = sqliteTable("messages", {
  id: text("id").primaryKey(), conversationId: text("conversation_id").notNull().references(() => conversations.id),
  senderId: text("sender_id").notNull().references(() => users.id), body: text("body").notNull(), createdAt: integer("created_at").notNull(),
}, t => [index("messages_conversation").on(t.conversationId, t.createdAt)]);
