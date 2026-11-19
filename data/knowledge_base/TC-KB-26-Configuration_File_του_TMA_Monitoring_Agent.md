# TC-KB-26: Configuration File του TMA Monitoring Agent

Category: Configuration
Device Models: APS COMPACT NL,APS CASHLESS TTW
Knowledge Status: Approved
Knowledge Type: FAQ
Language: English-Greek
Operational Status: Degraded
Product: TotalCare
Solution Status: Verified

Created By: ioabuh
Last Edited By: ioabuh
Revision: 2
Created At: 2026-11-11T12:48:40Z
Updated At: 2026-11-11T12:48:41Z

## CORRECT CONFIGURATION FILE OF TMA AGENT

Παρακάτω παρουσιάζετε ο σωστός τρόπος ρύθμισης του TMA agent για την σύνδεση και επικοινωνία με το TotalCare.

```
<TMAConfig>
	<FileClearence>
		<FileClearenceRule>
			<Directory>C:\Unixfor\Kiosk\atmmsg\</Directory>
			<Extension>txt</Extension>
			<MaxDays>5</MaxDays>
		</FileClearenceRule>
		<FileClearenceRule>
			<Directory>C:\Unixfor\Kiosk\Logs\</Directory>
			<Extension>log</Extension>
			<MaxDays>700</MaxDays>
		</FileClearenceRule >
	</FileClearence>

	<StoreNForwardMaxTimeSpanSecs>60</StoreNForwardMaxTimeSpanSecs>
	
	<TotalCareServers>
           <Server>
              <Name>Primary</Name>
              <URL>https://totalcare-main-gw.unixfor.gr</URL>
              <WS>wss://totalcare-main-tma.unixfor.gr/tc/ws</WS> 
              <UserName>6180DEH1</UserName>
              <Password>xxxxxx</Password>
              <LogInAPI>https://totalcare-main-tma.unixfor.gr/api/v1/tma/login</LogInAPI> 
           </Server>
     </TotalCareServers>

	<LoggingLevel>DEBUG</LoggingLevel>

	<Timers>
		<InitialialWaitTime>10</InitialialWaitTime>
		<RespawnDelay>5</RespawnDelay>
	</Timers>
</TMAConfig>
```

## TOTALCARE MESSAGES

Δεν υπάρχουν μηνύματα στο TotalCare. Η σύνδεση δεν πραγματοποιείται ποτέ.

## DIAGNOSTIC PROCEDURE

Πρόσβαση στο σύστημα και έλεγχος του configuration και του δικτύου.

## VERIFICATION

1. TMA websockets URL `ss://totalcare-main-tma.unixfor.gr/tc/ws`
2. TMA secure login API URL `https://totalcare-main-tma.unixfor.gr/api/v1/tma/login`

## REQUIRED INFORMATION FOR FURTHER DIAGNOSIS

Αν ο TMA μετά από τους παραπάνω ελέγχους πάλι δεν συνδεεται με το TotalCare, επικοινωνίστε με την UNIXFOR.

## RELATED QUESTIONS

Πως θα στησω σωστά τον TMA Agent
Παράδειγμα setup του TMA
Αρχειο παραμετροποίησης του TMA TerminalMonitoringAgent.xml
Ο TMA agent δεν συνδέεται με το TotalCare
To login του TMA agent αποτυγχάνει.

## SOLUTIONS

### Solution 1: First solution

**Prerequisites:**
Πρόσβαση στο configuration file του TotalCare
**Resolution steps:**

1. Βεβαιωθείται ότι το APS έχει σύνδεση στο internet.
2. Βεβαιωθείται ότι μπορείτε να κάνετε ping το gateway του καταστήματος.
3. Βεβαιωθείται ότι μπορείτε να κάνετε ping το DNS 8.8.8.8
4. Βεβαιωθείτε ότι το totalcare-main-tma.unixfor.gr κάνει resolve στο 212.205.55.154 κάνωντας ping `ping totalcare-main-tma.unixfor.gr`
5. Βεβαιωθείτε ότι το username και το password είναι σωστά
6. Βεβαιωθείτε ότι το url των websockets είναι σωστό -> wss://totalcare-main-tma.unixfor.gr/tc/ws
7. Βεβαιωθείτε ότι το url του totalCare API είναι σωστό -> https://totalcare-main-tma.unixfor.gr/api/v1/tma/login
**Expected result:**

Να συνδεθεί με το websocket και να στέλνει μηνύματα στο TotalCare
