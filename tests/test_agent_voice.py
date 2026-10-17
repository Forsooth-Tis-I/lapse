from lapse.agent import guard


def test_unknown_service_copy_is_honest_and_grounded():
    result = {
        "outcome": "not_in_graph",
        "account": {"id": "splitwise-personal", "display": "Splitwise · you@example.com", "modelled": False},
        "service": {"name": "Splitwise", "modelled": False},
    }
    answer = guard.templated([result])
    assert answer == "I don't know how <b>Splitwise</b> lets people back in, so I can't promise it's safe."
    assert guard.grounded(answer, [result])
    assert not guard.grounded(answer.replace("Splitwise", "Spotify"), [result])


def test_missing_account_does_not_invent_a_name():
    answer = guard.templated([{"outcome": "not_in_graph", "candidates": [], "message": "Unknown, not safe."}])
    assert answer == (
        "I haven't found that account or contact yet, so I can't tell you whether it's safe. "
        "Which email, number, or service do you mean?"
    )


def test_grounding_accepts_display_label_parts_and_html_escaped_names():
    results = [{"account": {"display": "Google · you@example.com"}}, {"name": "A&B"}]
    assert guard.grounded("Your <b>Google account</b> (you@example.com) is at risk.", results)
    assert guard.grounded("<b>A&amp;B</b> is at risk.", results)
    assert not guard.grounded("Your Google account (other@example.com) is at risk.", results)


def test_explanation_preserves_all_required_inputs_together():
    answer = guard.templated(
        [
            {
                "outcome": "path",
                "steps": [
                    {
                        "from_id": "mail",
                        "from_label": "Gmail",
                        "to_id": "notion",
                        "to_label": "Notion",
                        "method_id": "both",
                    },
                    {
                        "from_id": "phone",
                        "from_label": "••4321",
                        "to_id": "notion",
                        "to_label": "Notion",
                        "method_id": "both",
                    },
                ],
            }
        ]
    )
    assert answer == "Someone needs <b>Gmail</b> and <b>••4321</b> to get into <b>Notion</b> this way."


def test_html_in_graph_labels_is_escaped_and_ids_stay_hidden():
    answer = guard.templated(
        [
            {
                "outcome": "not_in_graph",
                "account": {"id": "internal-account-id", "display": "<script>"},
            }
        ]
    )
    assert "<b>&lt;script&gt;</b>" in answer
    assert "internal-account-id" not in answer
    assert "<script>" not in answer


def test_real_scenario_cards_are_grounded_without_accepting_invented_entities():
    from datetime import date

    from lapse.bot.cards import scenario_card
    from lapse.contracts import Reached, Root, ScenarioResult

    phone = Root(
        id="phone_old",
        kind="phone",
        status="retiring",
        label="••9810 (Vi)",
        last4="9810",
        carrier="vi_in",
        drop_at=date(2026, 10, 31),
        reissue_after=date(2027, 1, 29),
    )
    college = Root(
        id="email_college",
        kind="email",
        status="closing",
        label="aanya.nyu@gmail.com",
        address="aanya.nyu@gmail.com",
        email_kind="edu",
        hosted_by_service="google",
        closes_at=date(2026, 11, 15),
    )
    google = Reached(
        node_id="google_personal", label="Google · aanyapersonal61@gmail.com", node_type="Account", round=1
    )
    figma = Reached(node_id="figma", label="Figma · aanyapersonal61@gmail.com", node_type="Account", round=2)
    notion = Reached(
        node_id="notion", label="Notion · aanyapersonal61@gmail.com", node_type="Account", round=2
    )
    college_google = Reached(
        node_id="google_college", label="Google · aanya.nyu@gmail.com", node_type="Account", round=1
    )
    reassigned = ScenarioResult(
        id="scenario_phone",
        kind="takeover",
        root_ids=[phone.id],
        actor="stranger",
        rounds=2,
        affected_accounts=[google, figma, notion],
        direct_accounts=[google.node_id],
        unknown_accounts=[],
        total_accounts=4,
        ms=1,
    )
    closing = ScenarioResult(
        id="scenario_email",
        kind="lockout",
        root_ids=[college.id],
        actor="user",
        rounds=1,
        affected_accounts=[college_google],
        lost_now_accounts=[college_google],
        recovery_lost_accounts=[college_google],
        direct_accounts=[college_google.node_id],
        unknown_accounts=[],
        total_accounts=4,
        ms=1,
    )
    accounts = [
        {
            "id": "notion",
            "display": notion.label,
            "identifier": "aanyapersonal61@gmail.com",
            "previous_identifiers": [college.address],
        }
    ]
    for root, scenario in [(phone, reassigned), (college, closing)]:
        answer = scenario_card(root, scenario, today=date(2026, 10, 18), accounts=accounts)
        results = [root.model_dump(mode="json"), scenario.model_dump(mode="json"), accounts]
        assert guard.grounded(answer, results), answer
        assert not guard.grounded(answer.replace("Google", "Spotify"), results)
        assert not guard.grounded(answer.replace("aanya", "unseen"), results)
        assert not guard.grounded(answer + " Your number is 1234.", results)
        assert not guard.grounded(answer + " Your number is ••1234.", results)
    assert guard.grounded("Your old Vi number (••9810) is at risk.", [phone.model_dump(mode="json")])
    assert not guard.grounded("Your old Airtel number (••9810) is at risk.", [phone.model_dump(mode="json")])
