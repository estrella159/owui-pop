from owui_pop.render import for_display, line_breaks, maths


def test_single_line_breaks_stay_line_breaks():
    md = "**Working:**\n\n° C = (72 − 32) × 5/9\n° C = 40 × 5/9\n° C = 200/9"
    assert line_breaks(md) == "**Working:**\n\n° C = (72 − 32) × 5/9  \n° C = 40 × 5/9  \n° C = 200/9"


def test_code_lists_tables_and_headings_are_left_alone():
    md = "```\na\nb\n```\n- one\n- two\n| a | b |\n|---|---|\n# Title\ntext"
    assert line_breaks(md) == md


def test_maths_blocks_become_text_but_dollars_stay():
    assert maths(r"\( 22.2^\circ\text{C} \approx \frac{200}{9} \)") == "22.2°C ≈ 200/9"
    assert maths(r"$$ x = \frac{a+b}{2} \times \sqrt{y} $$") == "x = (a+b)/2 × √(y)"
    assert maths("It costs $5 and $10.") == "It costs $5 and $10."


def test_for_display_does_both():
    assert for_display("a\n\\(1 \\times 2\\)") == "a  \n1 × 2"
