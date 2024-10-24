from .stripe_kyc_provider import StripeKYCProvider
from .internal_kyc_provider import INTERNAL_KYC_PROVIDER
from .sumsub_kyc_provider import SumsubKYCProvider

SUMSUB_KYC_PROVIDER = SumsubKYCProvider()

KYC_PROVIDERS = {
    "Stripe": StripeKYCProvider(),
    "Windapp": INTERNAL_KYC_PROVIDER,
    "Sumsub": SUMSUB_KYC_PROVIDER,
}
