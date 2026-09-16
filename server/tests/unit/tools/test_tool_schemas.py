import pytest
from pydantic import ValidationError

from app.tools.schemas import CheckPaymentInput, CreateTicketInput, GetCustomerInput


def test_get_customer_input_accepts_customer_id() -> None:
    payload = GetCustomerInput.model_validate({"customer_id": "  cus_123  "})

    assert payload.customer_id == "cus_123"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"customer_id": ""},
        {"customer_id": 123},
        {"customer_id": "cus_123", "unexpected": True},
    ],
)
def test_get_customer_input_rejects_invalid_arguments(arguments: object) -> None:
    with pytest.raises(ValidationError):
        GetCustomerInput.model_validate(arguments)


def test_check_payment_requires_customer_or_account_id() -> None:
    assert CheckPaymentInput.model_validate({"customer_id": "cus_123"}).customer_id
    assert CheckPaymentInput.model_validate({"account_id": "acct_123"}).account_id

    with pytest.raises(ValidationError, match="customer_id or account_id"):
        CheckPaymentInput.model_validate({})


def test_create_ticket_input_rejects_extra_and_invalid_priority() -> None:
    payload = CreateTicketInput.model_validate(
        {
            "customer_id": "cus_123",
            "title": "Billing issue",
            "description": "The caller needs a receipt.",
            "priority": "high",
        }
    )

    assert payload.priority == "high"

    with pytest.raises(ValidationError):
        CreateTicketInput.model_validate(
            {
                "customer_id": "cus_123",
                "title": "Billing issue",
                "description": "The caller needs a receipt.",
                "priority": "whenever",
            }
        )

    with pytest.raises(ValidationError):
        CreateTicketInput.model_validate(
            {
                "customer_id": "cus_123",
                "title": "Billing issue",
                "description": "The caller needs a receipt.",
                "unexpected": True,
            }
        )
