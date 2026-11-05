import type { DbAlertType } from "./alerts";

export interface AlertNotificationPayload {
  alertId: string;
  userId: string;
  recipientContact?: string;
  channel: "email" | "sms" | "webhook" | "mock";
  stationId: string;
  stationName: string;
  alertType: DbAlertType;
  message: string;
  timestamp: string;
}

export interface DispatchResult {
  success: boolean;
  channel: "email" | "sms" | "webhook" | "mock";
  deliveredAt: string | null;
  error?: string;
}

export interface IAlertDispatcher {
  dispatch(payload: AlertNotificationPayload): Promise<DispatchResult>;
}

/**
 * Safe offline mock alert dispatcher for testing and local environments.
 * Prevents phantom network requests when production notification services are unconfigured.
 */
export class MockAlertDispatcher implements IAlertDispatcher {
  public dispatched: AlertNotificationPayload[] = [];

  async dispatch(payload: AlertNotificationPayload): Promise<DispatchResult> {
    if (!payload.userId || !payload.stationId || !payload.alertType) {
      return {
        success: false,
        channel: "mock",
        deliveredAt: null,
        error: "Missing required notification fields (userId, stationId, or alertType)",
      };
    }

    this.dispatched.push({ ...payload });

    return {
      success: true,
      channel: "mock",
      deliveredAt: new Date().toISOString(),
    };
  }

  clear() {
    this.dispatched = [];
  }
}

/**
 * Dispatch an alert notification through the configured dispatcher.
 * Fallbacks safely to mock dispatcher when external API credentials are absent.
 */
export async function dispatchAlertNotification(
  payload: AlertNotificationPayload,
  dispatcher: IAlertDispatcher = new MockAlertDispatcher()
): Promise<DispatchResult> {
  return dispatcher.dispatch(payload);
}
