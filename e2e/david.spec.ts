import { test, expect } from "@playwright/test";

test("David finds the cheapest pickup on the frontier", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "Pickups" }).click();
  await expect(page.getByText(/Frontier · \d+ of 19 undominated/)).toBeVisible();

  await page.getByRole("button", { name: "Minimum cost" }).click();
  await expect(page.getByRole("button", { name: "Minimum cost" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("PRESET: MINIMUM COST")).toBeVisible();
  await expect(page.getByRole("button", { name: /^01 Ford Maverick Hybrid/ })).toBeVisible();
});
