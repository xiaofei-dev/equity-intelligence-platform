export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({
    service: "frontend",
    status: "UP",
  });
}
