export const UNCONFIRMED = 'foreground_shutdown_unconfirmed';

// SDK57's public remove() unsubscribes JS but returns no native acknowledgement.
export class ForegroundWatch {
  private subscription: { remove(): void } | undefined;
  unconfirmed = false;
  begin() { this.unconfirmed = true; }
  attach(subscription: { remove(): void }) { this.subscription = subscription; }
  close() {
    const subscription = this.subscription;
    this.subscription = undefined;
    subscription?.remove();
    // Never clear this latch based on a void return, including subsequent Stop.
  }
}
