/**
 * AWS adapter for DynamoStore. The SDK is an optional dependency, imported only
 * when COVEN_STORE=dynamo, so local development needs no AWS packages.
 *
 * Not exercised against real DynamoDB by the test suite (DynamoStore is tested
 * against an in-memory TableClient); verify with a real table before relying on it.
 */

import type { Json } from "./events.ts";
import type { TableClient } from "./store.ts";

export async function awsTable(tableName: string): Promise<TableClient> {
  let lib: any;
  let client: any;
  try {
    lib = await import("@aws-sdk/lib-dynamodb");
    client = await import("@aws-sdk/client-dynamodb");
  } catch {
    throw new Error("COVEN_STORE=dynamo needs @aws-sdk/client-dynamodb and @aws-sdk/lib-dynamodb (npm install)");
  }
  const doc = lib.DynamoDBDocumentClient.from(new client.DynamoDBClient({}), {
    marshallOptions: { removeUndefinedValues: true },
  });

  return {
    async putEvent(item: Json) {
      try {
        await doc.send(new lib.PutCommand({
          TableName: tableName,
          Item: item,
          ConditionExpression: "attribute_not_exists(pk)",
        }));
        return "stored";
      } catch (error) {
        if ((error as Error).name === "ConditionalCheckFailedException") return "exists";
        throw error;
      }
    },
    async putRun(item: Json) {
      await doc.send(new lib.PutCommand({ TableName: tableName, Item: item }));
    },
    async scanAll() {
      const items: Json[] = [];
      let key: Json | undefined;
      do {
        const page: any = await doc.send(new lib.ScanCommand({ TableName: tableName, ExclusiveStartKey: key }));
        items.push(...(page.Items ?? []));
        key = page.LastEvaluatedKey;
      } while (key);
      return items;
    },
  };
}
