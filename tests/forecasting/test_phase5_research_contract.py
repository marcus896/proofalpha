import unittest


@unittest.skip("Private planning/provenance contract documents are intentionally excluded from the public ProofAlpha export.")
class Phase5TimesFmResearchContractTests(unittest.TestCase):
    def test_private_contract_documents_are_not_public_export_inputs(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
