import { test, expect } from "@playwright/test";

test("smoke: planner loads with no console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Where the trade-offs stop trading" })).toBeVisible();
  expect(errors).toEqual([]);
});
