const mcp = require("@modelcontextprotocol/sdk");
const { NotionAPI } = require("notion-client");

async function main() {
  const server = new mcp.StdioServer();

  // Initialize Notion client
  const token = process.env.NOTION_TOKEN || process.env.NOTION_TOKEN_PATH;
  let notionClient;

  if (token && token.startsWith("secret_")) {
    // Direct token
    notionClient = new NotionAPI({ authToken: token });
  } else {
    // Token from file path
    const fs = require("fs");
    const tokenContent = fs.readFileSync(token, "utf-8").trim();
    notionClient = new NotionAPI({ authToken: tokenContent });
  }

  // List databases
  server.setRequestHandler(mcp.CoreRequestType.ListTools, async () => {
    return {
      tools: [
        {
          name: "notion-search",
          description: "Search Notion workspace pages and databases",
          inputSchema: {
            type: "object",
            properties: {
              query: { type: "string", description: "Search query" }
            },
            required: ["query"]
          }
        },
        {
          name: "notion-query-database",
          description: "Query a specific Notion database",
          inputSchema: {
            type: "object",
            properties: {
              database_id: { type: "string", description: "Notion Database ID" },
              filter: { type: "object", description: "Optional filter" },
              sorts: { type: "array", description: "Optional sort criteria" }
            },
            required: ["database_id"]
          }
        },
        {
          name: "notion-create-page",
          description: "Create a new page in Notion",
          inputSchema: {
            type: "object",
            properties: {
              parent: { type: "object", description: "Parent database or page" },
              properties: { type: "object", description: "Page properties" },
              children: { type: "array", description: "Page content blocks" }
            },
            required: ["parent", "properties"]
          }
        }
      ]
    };
  });

  // Handle tool calls
  server.setRequestHandler("notion-search", async ({ params }) => {
    const { query } = params;
    try {
      const results = await notionClient.search({ query });
      return { content: results };
    } catch (error) {
      return { error: error.message };
    }
  });

  server.setRequestHandler("notion-query-database", async ({ params }) => {
    const { database_id, filter, sorts } = params;
    try {
      const response = await notionClient.queryDatabase(database_id, {
        filter,
        sorts
      });
      return { content: response };
    } catch (error) {
      return { error: error.message };
    }
  });

  server.setRequestHandler("notion-create-page", async ({ params }) => {
    const { parent, properties, children } = params;
    try {
      const response = await notionClient.pages.create({
        parent,
        properties,
        children
      });
      return { content: response };
    } catch (error) {
      return { error: error.message };
    }
  });

  await server.run();
}

main().catch(console.error);
