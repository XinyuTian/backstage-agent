from backstage_agent.models import ProjectNotice
from backstage_agent.project_page_parser import parse_project_page_roles


def test_parse_project_page_roles_from_expanded_backstage_text():
    project = ProjectNotice(
        source_message_id="m1",
        title="Lunar 5",
        project_url="https://example.com/lunar",
        description='Casting "LUNAR 5," an animated series.',
        raw_text='Casting "LUNAR 5," an animated series.',
        project_labels=["Animation"],
    )
    html = """
<main>
<p>Seeking talent Worldwide</p>
<h2>Roles in this project</h2>
<p>Collapse All Roles</p>
<p>ACTORS &amp; PERFORMERS</p>
<p>Dan</p>
<p>WORK-FROM-HOME</p>
<p>Lead. 18-50</p>
<button>Apply</button>
<p>Captain of the LUNAR 5 and father of Michael and Sarah.</p>
<p>Pre-Screen Requests:Video, 3 Question(s)</p>
<p>Rate: $500 flat rate</p>
<p>Total Pay: $500 (est. 4 hours of work)</p>
<p>Share</p>
<p>Clara</p>
<p>Lead. 18-60</p>
<button>Apply</button>
<p>Scientist and mission strategist.</p>
<h2>Dates &amp; Locations</h2>
<p>Remote.</p>
<h2>Compensation &amp; Contract</h2>
<p>Dan: Lead</p>
<p>Rate: $500 flat rate</p>
<p>Total Pay: $500 (est. 4 hours of work)</p>
<p>Clara: Lead</p>
<p>Rate: $500 flat rate</p>
<p>Total Pay: $500 (est. 4 hours of work)</p>
</main>
"""

    roles = parse_project_page_roles(project, html)

    assert [role.title for role in roles] == ["Lunar 5 - Dan", "Lunar 5 - Clara"]
    assert roles[0].location == "Seeking talent Worldwide"
    assert roles[0].project_labels == ["Animation"]
    assert "Captain of the LUNAR 5" in roles[0].description
    assert "Rate: $500 flat rate" in roles[1].compensation


def test_parse_project_page_roles_adds_backstage_page_labels():
    project = ProjectNotice(
        source_message_id="m1",
        title="Behind The Confessional",
        project_url="https://example.com/confessional",
        description='Casting "Behind The Confessional."',
        raw_text='Casting "Behind The Confessional."',
    )
    html = """
<main>
<p>FEATURE FILM</p>
<p>NONUNION</p>
<p>Posted 1 day ago</p>
<h1>'Behind The Confessional'</h1>
<h2>Roles in this project</h2>
<p>Zella Marchand</p>
<p>Lead. Female. 18-35</p>
<p>A conflicted believer facing buried trauma.</p>
<h2>Dates &amp; Locations</h2>
<p>Remote.</p>
</main>
"""

    roles = parse_project_page_roles(project, html)

    assert roles[0].title == "Behind The Confessional - Zella Marchand"
    assert roles[0].project_labels == ["FEATURE FILM"]
