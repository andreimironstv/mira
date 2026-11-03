import { RecoveryScreen } from "./RecoveryScreen";

export function RelaunchRequiredScreen() {
  return (
    <RecoveryScreen
      testId="relaunch-required"
      title="Restart Mira to finish recovery"
      body="Your identity was updated. Mira needs to restart so syncing and agents run under it."
    />
  );
}
