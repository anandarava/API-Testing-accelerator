/** Runs registered cleanup steps after a test, newest first, even when the test failed. */
export class Cleanup {
  private readonly steps: { label: string; run: () => Promise<unknown> }[] = [];

  add(label: string, run: () => Promise<unknown>): void {
    this.steps.push({ label, run });
  }

  async runAll(): Promise<string[]> {
    const failures: string[] = [];
    for (const step of this.steps.reverse()) {
      try {
        await step.run();
      } catch (error) {
        failures.push(`${step.label}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    this.steps.length = 0;
    return failures;
  }
}
