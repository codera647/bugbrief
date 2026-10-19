"""Optional runtime integration: run after installing requirements-model.in."""
import copy
import json

import pytest

lm = pytest.importorskip("lmformatenforcer", reason="Optional model runtime is not installed")
from app.domain import Ticket
from app.inference import examples


def accepted(text):
    parser = lm.JsonSchemaParser(Ticket.model_json_schema())
    for character in text:
        if character not in parser.get_allowed_characters():
            return False
        parser = parser.add_character(character)
    return parser.can_end()


def test_schema_constraints_accept_valid_tickets_and_reject_observed_shape_errors():
    for example in examples():
        assert accepted(json.dumps(example['ticket']))
    payload = copy.deepcopy(examples()[0]['ticket'])
    payload.pop('follow_up_questions')
    assert not accepted(json.dumps(payload))
    payload = copy.deepcopy(examples()[0]['ticket'])
    payload['reported_steps'] = 'Open the page.'
    assert not accepted(json.dumps(payload))
    payload = copy.deepcopy(examples()[0]['ticket'])
    payload['follow_up_questions'] = ['Question one?', 'Question two?', 'Question three?', 'Question four?']
    assert not accepted(json.dumps(payload))
