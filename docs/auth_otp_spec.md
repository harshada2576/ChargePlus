# Authentication & OTP Specification and Regulatory Compliance

## Overview

ChargePlus supports two primary authentication modes:
1. **Production Mode (`NEXT_PUBLIC_DEMO_MODE="false"`)**: Authenticates exclusively via Supabase Auth using configured external SMS/Email providers. Strict fail-closed semantics are enforced; missing SMS configuration returns an explicit error with troubleshooting guidance. No synthetic accounts or universal OTP bypasses exist in production.
2. **Development / Demo Simulator (`NEXT_PUBLIC_DEMO_MODE="true"`)**: Employs an in-memory, deterministic OTP simulator for controlled end-to-end testing without external network or provider dependencies.

---

## 1. Controlled Test Accounts (Development / Demo Only)

When `NEXT_PUBLIC_DEMO_MODE="true"`, developers and automated test harnesses can use controlled test accounts:

| Role | Phone Number | Fixed Test Code | Session Type | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **EV Driver** | `+919876543210` | `123456` | Mock Driver Session | Standard consumer profile |
| **Station Operator / Admin** | `+919876543219` | `123456` | Mock Admin Session | Operator role with station management |
| **Arbitrary Phone (Dev)** | Any valid E.164 | Ephemeral 6-digit | Ephemeral Mock | Code displayed in dev console; expires in 5 min |

### Safeguards:
- Controlled test accounts and the simulator are **completely bypassed and rejected in production**. `simulateDevVerifyOtp` and `simulateDevSendOtp` immediately throw if called when `isDemoMode()` is false.
- **Expiry**: Generated simulator OTPs expire after 300 seconds (5 minutes).
- **Max Attempts**: Maximum 3 incorrect attempts allowed per challenge before the verification token is revoked (lockout).
- **Zero Secret Exposure**: No service-role keys or OTPs are logged in production console streams.

---

## 2. Production Authentication Flow & Fallback Architecture

In production (`NEXT_PUBLIC_DEMO_MODE="false"`):

```
       [User Input (Phone E.164)]
                   │
                   ▼
     [supabase.auth.signInWithOtp]
                   │
         ┌─────────┴─────────┐
         │                   │
    [Success]           [Error (Provider/Config)]
         │                   │
         ▼                   ▼
 [Awaiting SMS OTP]     [Actionable Error Message]
                             │
                             ▼
                     [Email OTP Fallback Prompt]
                     ("Try logging in with email")
```

### Supported Providers:
- **Phone OTP**: Twilio, MessageBird, or Vonage configured via Supabase Dashboard -> Authentication -> Phone Auth.
- **Email OTP / Magic Link**: Fallback mechanism when SMS provider is degraded or unconfigured. Uses Supabase Built-in SMTP or custom SendGrid/Resend SMTP.

### Missing SMS Configuration Behavior:
If an operator hasn't configured a phone provider in Supabase, the Supabase client returns `sms_provider_not_configured` or `provider_disabled`. `safeMessage()` maps this directly to:
> *"SMS authentication provider is not configured in Supabase. Please configure Twilio or MessageBird in your Supabase Auth dashboard, or use email login."*

---

## 3. Indian SMS Regulatory Compliance (TRAI TCCCPR 2018)

Deploying real SMS OTP delivery in India requires compliance with Telecom Regulatory Authority of India (TRAI) Telecom Commercial Communications Customer Preference Regulations, 2018 (TCCCPR).

### Mandatory Regulatory Steps:
1. **Distributed Ledger Technology (DLT) Registration**:
   - The business entity must register as a **Principal Entity (PE)** on an authorized Indian telecom DLT portal (e.g., Jio DLT, Airtel DLT, Vodafone Idea DLT, or Tata DLT).
   - Requires corporate PAN, GSTIN, Certificate of Incorporation, and authorized signatory KYC.
   - Non-refundable registration fee: ~₹5,900 (one-time).
2. **Sender ID / Header Registration**:
   - Register a 6-character alphabetic Sender Header under the "Service Implicit / Transactional" category (e.g., `CHRGPS` or `CRGPLS`).
   - Annual header renewal fee: ~₹1,000–₹2,000 depending on operator.
3. **Content Template Registration**:
   - Pre-register the exact OTP message template with dynamic variables (`{#var#}`):
     ```text
     Your ChargePlus verification code is {#var#}. Valid for 5 minutes. Do not share this OTP with anyone. - ChargePlus
     ```
   - Template category: **Service Implicit** (ensures delivery 24/7 to DND-registered mobile numbers without scrubbing restrictions).
   - Telemarketer binding with provider (e.g., Twilio / SMS Country / Kaleyra / Gupshup).
4. **Estimated Delivery Costs (INR)**:
   - DLT Scrubbing Charge: ~₹0.12 per SMS.
   - Telecom Carrier SMS Charge: ~₹0.15 to ₹0.25 per SMS.
   - Effective cost per OTP: ~₹0.27 to ₹0.40 INR.

---

## 4. Test Execution & Verification

Automated regression tests in `tests/test_auth_otp.mjs`:
- Verified simulator respects controlled test numbers and codes.
- Verified incorrect code rejection and failure tracking.
- Verified lockout after 3 consecutive failures.
- Verified token expiry after 300 seconds.
- Verified safe parsing of provider missing/degraded error codes.
