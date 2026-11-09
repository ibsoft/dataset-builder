# TC-KB-03: Kiosk Communication Lost

Category: Connectivity
Device Models: APS Compact, APS Cashless
Knowledge Status: Draft
Knowledge Type: Troubleshooting
Language: English
Operational Status: SPCommunicationDown
Product: TotalCare
Solution Status: Diagnostic Only

Created By: admin
Last Edited By: admin
Revision: 2
Created At: 2026-11-09T12:31:16Z
Updated At: 2026-11-09T12:31:27Z

## PROBLEM DESCRIPTION

A kiosk may lose communication with the TotalCare monitoring platform.

TotalCare monitoring communication is handled through the TMA Agent.

A communication failure can prevent TotalCare from receiving current monitoring information.

Missing monitoring messages do not necessarily mean that the kiosk is powered off or unable to perform transactions.

## POSSIBLE SYMPTOMS

The following symptoms may indicate a communication problem:

1. The kiosk is reported as disconnected from TotalCare.
2. No recent monitoring messages are available.
3. The last communication timestamp is older than expected.
4. The stored operational status may indicate SPCommunicationDown.

These are possible symptoms and must not be interpreted as confirmed conditions without checking the affected kiosk.

## POSSIBLE CAUSES

### 1. Network Connectivity Failure

A network connectivity problem may prevent communication between the kiosk and the TotalCare platform.

### 2. Monitoring Agent Failure

The TMA monitoring agent may have stopped operating or may not be communicating correctly.

### 3. Communication Service Failure

A communication service involved in exchanging monitoring information may be malfunctioning.

### 4. Server-Side Communication Problem

A problem affecting the TotalCare communication infrastructure may prevent monitoring information from being received.

## DIAGNOSTIC PROCEDURE

### Step 1: Identify the Affected Kiosk

Obtain the kiosk identification code.

Identify the installed kiosk model if the information is available.

### Step 2: Examine the Operational Status

Retrieve the latest operational status recorded by TotalCare.

Check whether SPCommunicationDown or another operational status is reported.

Remember that stored operational status does not independently establish real-time network connectivity.

### Step 3: Examine the Last Communication

Retrieve the timestamp of the last monitoring message.

Determine how long the kiosk has been without a new monitoring message.

Compare this interval with the expected monitoring frequency, if documented.

### Step 4: Examine Communication Errors

Retrieve recent monitoring messages and communication-related errors.

Look for evidence associated with communication failures.

Do not interpret unknown message codes as communication errors without authorized documentation.

### Step 5: Examine Other Kiosks

Determine whether other kiosks at the same location are experiencing similar symptoms.

Compare communication timestamps.

Multiple affected kiosks may suggest a shared connectivity or infrastructure problem.

### Step 6: Identify the Most Likely Cause

Correlate the operational status, last communication timestamp, monitoring events, and documented troubleshooting procedures.

Do not identify a confirmed root cause without sufficient evidence.

## CORRECTIVE ACTIONS

### Cause: Network Connectivity Failure

Check the kiosk network connection using the approved deployment-specific diagnostic procedure.

If connectivity is unavailable, follow the authorized network recovery procedure.

### Cause: Monitoring Agent Failure

Check whether the TMA Agent is operating using the approved service diagnostic procedure.

If the agent is stopped or malfunctioning, follow its authorized recovery instructions.

### Cause: Communication Service Failure

Inspect the relevant service errors and available diagnostic logs.

Follow the approved recovery procedure for the affected communication component.

### Cause: Server-Side Communication Problem

Determine whether multiple kiosks are affected.

Review the available server-side monitoring information.

Escalate to the responsible infrastructure support team when the evidence indicates a shared platform issue.

## RECOVERY PROCEDURE AVAILABILITY

This knowledge record provides initial diagnostic guidance.

It does not currently contain verified service commands, network configuration procedures, or component recovery instructions.

Those procedures must be added from approved technical documentation before this record can be considered a complete troubleshooting solution.

## VERIFICATION

After an approved corrective action:

1. Confirm that new monitoring messages are being received.
2. Examine the most recent communication timestamp.
3. Review the updated operational status.
4. Confirm that the original reported communication problem is no longer observed.

Do not assume that restored TotalCare monitoring communication proves that transaction processing or payment authorization is functioning.

## REQUIRED INFORMATION FOR FURTHER DIAGNOSIS

Kiosk identification code.

Approximate time when the problem started, if known.

Any available communication error messages.

## RELATED QUESTIONS

Why is my kiosk offline?

Why is my terminal disconnected?

Why has the kiosk stopped sending messages?

How do I fix a kiosk communication failure?

Why is TotalCare not receiving kiosk messages?

Kiosk not connected to TotalCare.

TotalCare communication lost.

Γιατί το μηχάνημα είναι offline;

Γιατί το kiosk δεν επικοινωνεί;

Πώς διορθώνω το πρόβλημα επικοινωνίας;
