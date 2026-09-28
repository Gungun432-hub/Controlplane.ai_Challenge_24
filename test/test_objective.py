"""Does the answer serve what the person was actually trying to do?

The check our mentor asked for, measured the way the harm gate and the judge are
measured: a battery of cases where an objective really is abandoned, and a larger
battery of ordinary good answers that must stay quiet. The false alarm is the
expensive error here — a checker that tells people their good answers ignored
them is a checker nobody leaves switched on.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from python.controlplane import objective as O                          # noqa: E402
from python.controlplane.purpose import (OBJECTIVE_UNSERVED,            # noqa: E402
                                         purpose)

SIR_QUESTION = (
    "My car wash station is two kilometres from my house, but I am a fitness "
    "freak and I want to burn 200 calories today. Should I walk to my car wash "
    "station or should I drive?")
SIR_ANSWER = (
    "Since you are a fitness freak, walking is the better choice. A two "
    "kilometre walk each way burns roughly 200 calories for most adults, so you "
    "would hit your target for the day.")


DEFEATED = [
 # sir's example, several phrasings
 ("My car wash station is two kilometres from my house, but I am a fitness freak and I want to burn 200 calories today. Should I walk to my car wash station or should I drive?",
  "Since you are a fitness freak, walking is the better choice. A two kilometre walk each way burns roughly 200 calories for most adults, so you would hit your target for the day."),
 ("I want to burn 200 calories today. Should I walk to my car wash station or drive?",
  "Walking is better for you. Two kilometres at a brisk pace burns about 100 calories, so a round trip gets you to 200."),
 ("My car wash place is 2 km away. I am a fitness freak and I want to burn 200 calories today, should I walk or should I drive?",
  "Walk. At a brisk pace you will burn close to 200 calories over the round trip and get some fresh air."),
 # same failure shape, other errands
 ("The pharmacy is one kilometre away and I need to collect my prescription, but I also want to hit 10000 steps today. Should I walk or take an auto?",
  "Walking is the better option for your step count. One kilometre is about 1300 steps, so a round trip gives you 2600 steps towards your goal."),
 ("I have to post this parcel at the post office before five, and I want to save money on travel. Should I take the metro or a cab?",
  "The metro is far cheaper than a cab for that distance, usually under fifty rupees against three hundred. Take the metro and you will save money."),
 ("I need to deposit this cheque at my bank branch and I would like to get some exercise. Is it better to cycle or drive?",
  "Cycling is the better choice for exercise. It burns around 300 calories an hour and you avoid parking hassles."),
]

# Ordinary good pairs that must NOT be flagged.
CLEAN = [
 ("I want to return an order that arrived damaged. What is the process?",
  "You can raise a return within seven days of delivery. Open the order in your account, select Return, choose Damaged on arrival, and upload a photo. A pickup is scheduled within two business days and the refund is issued once the item reaches the warehouse."),
 ("My car wash station is two kilometres from my house and I want to burn 200 calories today. Should I walk or drive?",
  "Walking two kilometres each way burns roughly 200 calories, so it would meet your target. One thing to weigh: if you are taking the car to the car wash, walking there leaves the car at home, so you would not get the wash done. If the wash is the point, drive there and walk somewhere else later, or walk to the wash and drive the car over afterwards."),
 ("I need to reset my password but I no longer have access to my old email. How do I do it?",
  "Use the Can't access this email link on the reset page. It asks for your registered phone number and the last four digits of the card on file, then sends a one time code by SMS so you can set a new password without the old email."),
 ("I am trying to close a support ticket but the customer has not replied in ten days. What is the policy?",
  "Tickets with no customer reply for seven days can be closed as Resolved - no response. Send the standard final follow up first, wait 48 hours, then close the ticket with that resolution code. The customer can reopen it for another thirty days."),
 ("What is the refund window for a subscription?",
  "Subscriptions can be refunded in full within fourteen days of the charge if usage is under two hours. After that the refund is prorated by the days remaining in the billing period."),
 ("I would like to escalate a complaint to a manager. Who should I contact?",
  "Escalations go to the duty manager for the queue. Tag the ticket with escalate-l2 and it appears in the duty manager's inbox within fifteen minutes. If it is urgent, also post in the shift channel."),
 ("Should I approve this invoice or hold it for review?",
  "Hold it for review. Invoices above two lakh rupees need a second approver under the finance policy, and this one is at 2.4 lakh, so approving it alone would breach the control."),
 ("I have to file the GST return by the twentieth and I want to avoid a late fee. What do I need?",
  "To file GSTR-3B by the twentieth you need the outward supplies summary, input tax credit from GSTR-2B, and the challan for any cash payment. Filing on the twentieth avoids the late fee of fifty rupees a day."),
 ("Can you help me draft a reply to a customer asking for a refund outside the window?",
  "Here is a draft: Thank you for writing in. Our refund window is fourteen days from purchase and your order was placed on the second of March, so a refund is not available. I can offer you a credit note worth the unused portion, valid for twelve months."),
 ("My laptop from the IT store is not booting and I need it working for a demo tomorrow. Should I raise a ticket or walk into the IT desk?",
  "Walk into the IT desk for something this urgent. Raise a P2 ticket first so there is a record, then take the laptop to the desk on the third floor; they keep loaner machines for demos and can swap the drive over the same day."),
 ("I want to understand the leave policy for a wedding in the family.",
  "You get twelve days of casual leave a year and can take up to five consecutively. Weddings in the immediate family also qualify for two days of special leave on top, approved by your manager."),
 ("Is it better to pay the vendor by NEFT or by cheque for this amount?",
  "NEFT is better for this vendor. It settles the same day for amounts under two lakh, gives you a UTR number for reconciliation, and avoids the three day clearing delay of a cheque."),
 ("What should I say to a candidate we are rejecting after the final round?",
  "Keep it short and specific: thank them for the time, say the panel chose a candidate whose experience matched the role more closely, offer to keep their profile on file, and do not list individual weaknesses unless they ask."),
 ("I need to renew the insurance on the office vehicle before it lapses on Friday. What documents are needed?",
  "You need the previous policy copy, the registration certificate, a valid pollution certificate, and the pan card of the registered owner. Renew the policy online before Friday and the cover continues without a break inspection."),
]

# The shape the subject rule reaches into: a possessive subject AND a choice,
# answered properly. These are the ones that must stay quiet.
CLEAN_EXTRA = [
 ("My invoice from the vendor is for 2.4 lakh rupees. Should I approve it myself or route it to a second approver?",
  "Route the invoice to a second approver. Anything above two lakh needs two signatures under the finance policy, so approving it yourself would breach the control even though the vendor is on the approved list."),
 ("My team is behind on the sprint by about four days. Should I add two people or cut scope?",
  "Cut scope. Adding people to a sprint already in flight usually slows the team further because of ramp up, so trimming the two lowest value stories is the safer way to land the sprint on time."),
 ("My refund request is still open after twelve days. Should I call support or reply on the existing ticket?",
  "Reply on the existing ticket. A refund request open past ten days is auto escalated when the customer replies, which puts it in front of a duty manager, whereas a call creates a second ticket and resets the clock."),
 ("My laptop is out of warranty and the battery is swollen. Should I get it repaired at the IT desk or claim it on insurance?",
  "Take the laptop to the IT desk first. A swollen battery is a safety issue and they replace it free even out of warranty, and their report is what an insurance claim would need anyway."),
 ("My monthly spend on the marketing tool is 18000 rupees and I want to cut costs. Should I downgrade the plan or drop seats?",
  "Drop seats rather than downgrade the marketing tool. The lower plan removes the approval workflow you rely on, while unused seats are billed at 1200 each, so removing five gets you most of the saving with no loss of function."),
 ("My car needs a service and I want to keep the weekend free. Should I book Friday evening or Monday morning?",
  "Book the car in on Friday evening. The service centre keeps it overnight and returns it Saturday morning, so the car is serviced and your weekend stays free, whereas a Monday slot takes a working day."),
]

CLEAN = CLEAN + CLEAN_EXTRA


# --------------------------------------------------------------- measured ---
def test_catches_every_defeated_objective():
    missed = [q for q, a in DEFEATED if not O.inspect(q, a).defeated]
    assert missed == [], f"{len(missed)}/{len(DEFEATED)} abandoned objectives not caught"


def test_no_false_alarm_on_ordinary_answers():
    flagged = [(q[:60], O.describe(O.inspect(q, a)))
               for q, a in CLEAN if O.inspect(q, a).defeated]
    assert flagged == [], f"{len(flagged)}/{len(CLEAN)} good answers wrongly flagged"


def test_the_check_is_cheap_enough_to_run_inline():
    pairs = DEFEATED + CLEAN
    started = time.perf_counter()
    for q, a in pairs:
        O.inspect(q, a)
    per_case_ms = (time.perf_counter() - started) * 1000 / len(pairs)
    assert per_case_ms < 5.0, f"{per_case_ms:.2f} ms per case is too slow for inline"


# ----------------------------------------------------- the mentor's case ----
def test_the_errand_is_what_gets_named():
    result = O.inspect(SIR_QUESTION, SIR_ANSWER)
    assert result.defeated and result.is_choice
    headline = result.headline
    assert headline is not None
    assert headline.kind == O.ERRAND
    assert "car wash" in headline.text
    # the fitness goal really was served, and we must not claim otherwise
    served = [o.text for o in result.objectives if o not in result.unserved]
    assert any("calories" in t for t in served)


def test_plain_english_names_the_thing_in_the_persons_own_words():
    sentence = O.describe(O.inspect(SIR_QUESTION, SIR_ANSWER))
    assert "car wash station" in sentence
    # no jargon: a person reads this without decoding anything
    for word in ("objective", "detector", "score", "risk", "unserved"):
        assert word not in sentence.lower()


def test_an_answer_that_holds_both_objectives_passes():
    good = ("Walking two kilometres each way burns roughly 200 calories, so it "
            "would meet your target. One thing to weigh: if you are taking the "
            "car to the car wash, walking there leaves the car at home, so the "
            "wash would not get done. Drive to the wash and walk elsewhere later.")
    assert not O.inspect(SIR_QUESTION, good).defeated


# ------------------------------------------------------------- behaviours ---
def test_an_origin_is_not_an_errand():
    """"two kilometres from my house" is where you started, not why you went."""
    kinds = {(o.kind, o.text) for o in O.objectives(SIR_QUESTION)}
    assert not any(text == "house" for _, text in kinds)


def test_a_possessive_alone_is_not_held_against_an_answer():
    """Only in the trade-off shape, where objectives get traded away."""
    question = "My laptop is not booting after the update. What should I try?"
    answer = ("Hold the power button for ten seconds, then boot with the F8 key "
              "held to reach recovery and choose Roll back the update. That "
              "clears the failed patch without losing your files.")
    result = O.inspect(question, answer)
    assert any(o.kind == O.SUBJECT for o in result.objectives)
    assert not result.defeated


def test_an_honest_decline_is_not_a_defeated_purpose():
    declined = ("I can't help with fitness planning. My purpose is to answer "
                "questions about our returns and refunds policy, so this falls "
                "outside what I can assist with.")
    result = O.inspect(SIR_QUESTION, declined)
    assert result.declined and not result.defeated


def test_a_plural_is_the_same_objective():
    assert O._related("demo", "demos")
    assert O._related("return", "returning")
    assert not O._related("car", "care")


def test_the_cost_family_closes_the_vocabulary_gap():
    """Somebody who asks to cut costs is answered with "the saving"."""
    assert O._related("costs", "saving")
    assert not O._related("costs", "walking")


def test_a_question_with_no_stated_objective_is_left_alone():
    result = O.inspect("What is the refund window?", "Fourteen days from purchase.")
    assert result.objectives == [] and not result.defeated


def test_too_little_answer_to_judge_says_nothing():
    assert not O.inspect(SIR_QUESTION, "Walk.").defeated


# ------------------------------------------- wired into the real detector ---
def test_the_detector_fires_with_no_sources_at_all():
    """The car-wash question has no governing document anywhere. That is the
    point: the omission check cannot see it, so this one has to run first."""
    result = purpose(answer=SIR_ANSWER, prompt=SIR_QUESTION, sources=[])
    assert OBJECTIVE_UNSERVED in result.labels
    assert result.score >= 0.6
    assert result.detail["purposeUnserved"] is True
    assert "car wash station" in result.detail["plainEnglish"]


def test_the_detector_stays_quiet_on_an_ordinary_question():
    result = purpose(answer="Returns are accepted within seven days of delivery.",
                     prompt="I want to return an order. What is the window?",
                     sources=["Returns are accepted within seven days of delivery."])
    assert OBJECTIVE_UNSERVED not in result.labels


# ---------------------------------------------------- the ledger's own race ---
class TestTheLedgerVerifiesItsOwnWrites:
    """A fresh ledger written by this build used to fail its own verification.

    Nothing was tampering with the file. The content hash was computed over the
    live decision record, and deferred verification — on a background pool —
    amends that same record when a slow detector lands. An amendment arriving
    between hashing the object and serialising it meant the bytes on disk were
    not the bytes that had been hashed, and the entry was born broken: /health
    reported `degraded`, `valid: false`, `reason: "content hash mismatch"`, at a
    different index every boot.

    An audit trail that says it is broken is worth less than no audit trail, so
    this is here to stay.
    """

    def _ledger(self, tmp_path):
        from python.controlplane.ledger import JsonlLedger
        return JsonlLedger(tmp_path / "ledger.jsonl", "test-key")

    def test_a_record_amended_after_the_append_does_not_break_the_chain(self, tmp_path):
        ledger = self._ledger(tmp_path)
        record = {"requestId": "r-1", "detectors": [{"detectorId": "grounding"}]}
        ledger.append({"receipt": record})
        # exactly what deferred verification does a moment later
        record["detectors"].append({"detectorId": "fairness"})
        record["verificationLatencyMs"] = 812.4
        assert ledger.verify()["valid"] is True

    def test_it_holds_while_a_background_thread_amends_every_record(self, tmp_path):
        import threading
        import time

        ledger = self._ledger(tmp_path)
        records = [{"i": i, "detectors": [{"detectorId": "grounding"}]}
                   for i in range(120)]
        stop = threading.Event()

        def amend():
            rounds = 0
            while not stop.is_set() and rounds < 100000:
                for r in records:
                    r["detectors"] = [{"detectorId": "fairness", "round": rounds}]
                    r["verificationLatencyMs"] = time.time()
                rounds += 1

        worker = threading.Thread(target=amend, daemon=True)
        worker.start()
        try:
            for r in records:
                ledger.append({"receipt": r})
        finally:
            stop.set()
            worker.join(timeout=2)

        result = ledger.verify()
        assert result["valid"] is True, result
        assert result["entries"] == len(records)

    def test_an_unserialisable_value_is_recorded_rather_than_losing_the_receipt(
            self, tmp_path):
        """A receipt that records something odd is worth far more than no receipt."""
        ledger = self._ledger(tmp_path)
        ledger.append({"receipt": {"at": object()}})
        assert ledger.verify()["valid"] is True
