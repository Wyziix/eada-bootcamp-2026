import { env } from "cloudflare:workers";
import { handleApi } from "../../../server/api.mjs";

export const dynamic = "force-dynamic";
const handle = (request: Request) => handleApi(request, env.DB);
export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
