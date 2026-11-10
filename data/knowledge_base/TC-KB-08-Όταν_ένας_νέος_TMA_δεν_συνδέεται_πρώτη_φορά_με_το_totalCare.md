# TC-KB-08: Όταν ένας νέος TMA δεν συνδέεται πρώτη φορά με το totalCare

Category: Connectivity
Device Models: 
Knowledge Status: Approved
Knowledge Type: Known issue
Language: English-Greek
Operational Status: SPCommunicationDown
Product: TotalCare
Solution Status: Verified

Created By: admin
Last Edited By: admin
Revision: 2
Created At: 2026-11-10T12:51:34Z
Updated At: 2026-11-10T12:51:36Z

## PROBLEM DESCRIPTION

Σε νέα εγκατάσταση ο TMA και εν συνεπεία το APS δεν συνδέεται στο TotalCare.

## POSSIBLE SYMPTOMS

Δεν βλέπουμε το Service Point στο TotalCare

## TOTALCARE MESSAGES

Χωρίς μηνύματα

## POSSIBLE CAUSES

1. To Service Point είναι απενεργοποιημένο
2. Δεν έχει δημιουργηθεί σωστά το username και το password του TMA.
3. Έχει δίνει τυπογραφικό λάθος στο configuration file του TMA.
4. Λανθασμένο URL σύνδεσης στο configuration του TMA

## DIAGNOSTIC PROCEDURE

1. Ελέγχω το δίκτυο του μηχανήματος
2. Ελέγχω αν κάνω ping τον Gateway του καταστήματος.
3. Ελέγχω το configuration file του TMA για τυπογραφικά λάθη.

## CORRECTIVE ACTIONS

Περνάω ξανά το configuration του TMA

## SOLUTIONS

### Solution 1: First solution

**Prerequisites:**

1. Επιβεβαίώνω ότι το setup του Service Point στο TotalCare

**Resolution steps:**

1. Επιβεβαιώνω ότι το Service Point είναι ενεργό στο TotalCare
2. Επιβεβαιώνω ότι το username/password είναι σωστά στο TotalCare
3. Επιβεβαιώνω ότι το username/password δεν έχει τυπογραφικό στο configuration file του TMA
4. Ελέγχω ότι το δίκτυο του καταστήματος είναι λειτουργικό
5. Ελέγχω της ρυθμίσεις δικτύου του καταστήματος.
6. Κάνω ping τον gateway του καταστήματος
7. Κάνω ping το DNS 8.8.8.8
8. Κάνω ping το totalcare-gw.unixfor.gr , θα πρέπει να απαντάει. 

**Expected result:**

Θα πρέπει να βλέπετε να φεύγουν μηνύματα στο log file του TMA

## VERIFICATION

Ελέγχω απο το Log του TMA αν συνδέθηκε και στέλνει μηνύματα.

## REQUIRED INFORMATION FOR FURTHER DIAGNOSIS

Αν το πρόβλημα δεν λυθεί, επικοινωνίστε με το τμήμα δικτύων της Unixfor

## RELATED QUESTIONS

Νέα εγκατάσταση Service Point δεν συνδέεται στο totalCare
Το Kiosk δεν συνδέεται στο totalCare
Ο ΤΜΑ δεν συνδέεται στο TotalCare
To Kiosk / Service Point δεν στέλνει μηνύματα στο TotalCare
