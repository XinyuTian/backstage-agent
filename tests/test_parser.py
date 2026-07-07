from backstage_agent.models import EmailMessage
from backstage_agent.parser import parse_casting_notices, parse_project_notices


def test_parse_casting_notice_from_plain_text():
    message = EmailMessage(
        message_id="m1",
        subject="Backstage casting",
        sender="Backstage",
        received_at=None,
        html="",
        text="""
Project: Bright Coffee Spot
Role: Barista
Location: Los Angeles, CA
Pay: $500/day
Seeking actor with improv and commercial acting experience.
Apply here: https://example.com/apply
""",
    )

    notices = parse_casting_notices(message)

    assert len(notices) == 1
    assert notices[0].project == "Bright Coffee Spot"
    assert notices[0].role == "Barista"
    assert notices[0].compensation == "$500/day"


def test_parse_digest_project_and_role_as_single_notice():
    message = EmailMessage(
        message_id="m2",
        subject="21 New Roles Available for basic filter - Jul 6",
        sender="Backstage",
        received_at=None,
        html="",
        text="""
Casting lead roles for "Behind the Confessional," an independent psychological horror film writtena nd directed by Hugues Gentillon, about faith, guilt, and buried trauma. It is a character-driven horror project emphasizing powerful performances over jump scares.
Seeking talent from:
Worldwide
Zella Marchand
Lead,   Female,    18-35
Apply
View All Matching Jobs
You're receiving this email because you're subscribed to Backstage.
""",
    )

    notices = parse_casting_notices(message)

    assert len(notices) == 1
    assert notices[0].title == "Behind the Confessional - Zella Marchand"
    assert notices[0].project == "Behind the Confessional"
    assert notices[0].role == "Zella Marchand"
    assert notices[0].location == "Worldwide"
    assert "Lead,   Female,    18-35" in notices[0].raw_text
    assert "You're receiving this email" not in notices[0].raw_text


def test_parse_digest_project_with_multiple_role_cards():
    message = EmailMessage(
        message_id="m3",
        subject="21 New Roles Available for basic filter - Jul 6",
        sender="Backstage",
        received_at=None,
        html="",
        text="""
Casting "LUNAR 5," an original cinematic science fiction animated series produced by STA Animation Studios using Unreal Engine and advanced digital character technology.
Seeking talent from:
Worldwide
Dan
Lead, 18-50
Estimated pay amount: $500 for 4 hours of work
Apply
Clara
Lead, 18-60
Estimated pay amount: $500 for 4 hours of work
Apply
Boxer
Supporting, 18-49
Estimated pay amount: $400 for 4 hours of work
Apply
Feature Film
Nonunion
Posted 1 day, 20 hours ago
'Behind The Confessional'
View All Matching Jobs
""",
    )

    notices = parse_casting_notices(message)

    assert [notice.title for notice in notices] == [
        "Lunar 5 - Dan",
        "Lunar 5 - Clara",
        "Lunar 5 - Boxer",
    ]
    assert [notice.role for notice in notices] == ["Dan", "Clara", "Boxer"]
    assert notices[0].project == "Lunar 5"
    assert notices[2].compensation == "Estimated pay amount: $400 for 4 hours of work"


def test_parse_first_digest_project_after_metadata_header():
    message = EmailMessage(
        message_id="m4",
        subject="21 New Roles Available for basic filter - Jul 6",
        sender="Backstage",
        received_at=None,
        html="",
        text="""
Backstage
21 new jobs
matching your search
basic filter
Scripted Show
$ Paid
Nonunion
Posted 1 day, 4 hours ago
Gay Audio Romance Project
IMPORTANT: Please submit a read as either Danny or Paul or your application will not be considered.
Seeking talent from:
Nationwide
Danny
Lead, Male, Gender-Nonconforming, Non-Binary (+1 more genders), 18-30
Estimated pay amount: $2500 for 10 hours of work
Apply
Paul
Lead, Male, Gender-Nonconforming, Non-Binary (+1 more genders), 18-30
Estimated pay amount: $2500 for 10 hours of work
Apply
Short Film
$ Paid
Nonunion
Posted 1 day, 11 hours ago
'Tejidos'
Casting "Tejidos," a character-driven family drama.
""",
    )

    notices = parse_casting_notices(message)

    assert [notice.title for notice in notices] == [
        "Gay Audio Romance Project - Danny",
        "Gay Audio Romance Project - Paul",
    ]
    assert notices[0].location == "Nationwide"
    assert notices[1].compensation == "Estimated pay amount: $2500 for 10 hours of work"


def test_parse_digest_assigns_apply_links_per_role():
    message = EmailMessage(
        message_id="m5",
        subject="21 New Roles Available for basic filter - Jul 6",
        sender="Backstage",
        received_at=None,
        text="",
        html="""
<html><body>
<p>Posted 1 day, 4 hours ago</p>
<p>Gay Audio Romance Project</p>
<p>Seeking talent from:</p>
<p>Nationwide</p>
<p>Danny</p>
<p>Lead, Male, 18-30</p>
<a href="https://example.com/apply-danny">Apply</a>
<p>Paul</p>
<p>Lead, Male, 18-30</p>
<a href="https://example.com/apply-paul">Apply</a>
</body></html>
""",
    )

    notices = parse_casting_notices(message)

    assert [notice.application_url for notice in notices] == [
        "https://example.com/apply-danny",
        "https://example.com/apply-paul",
    ]


def test_parse_digest_discovers_projects_without_screening_roles():
    message = EmailMessage(
        message_id="m6",
        subject="21 New Roles Available for basic filter - Jul 6",
        sender="Backstage",
        received_at=None,
        text="",
        html="""
<html><body>
<p>Posted 1 day, 4 hours ago</p>
<a href="https://example.com/project-a">Gay Audio Romance Project</a>
<p>Seeking talent from:</p>
<p>Nationwide</p>
<p>Danny</p>
<p>Lead, Male, 18-30</p>
<a href="https://example.com/apply-danny">Apply</a>
<p>Short Film</p>
<p>Posted 1 day, 11 hours ago</p>
<a href="https://example.com/project-b">'Tejidos'</a>
<p>Casting "Tejidos," a character-driven family drama.</p>
</body></html>
""",
    )

    projects = parse_project_notices(message)

    assert [(project.title, project.project_url) for project in projects] == [
        ("Gay Audio Romance Project", "https://example.com/project-a"),
        ("Tejidos", "https://example.com/project-b"),
    ]
