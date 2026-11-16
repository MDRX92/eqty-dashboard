// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {EQTYGuestbook} from "../src/EQTYGuestbook.sol";
import {TestEQTY} from "../src/TestEQTY.sol";

contract EQTYGuestbookTest is Test {
    TestEQTY token;
    EQTYGuestbook book;
    address alice = address(0xA11CE);
    address bob = address(0xB0B);
    uint256 constant FEE = 100 ether;

    event Posted(uint256 indexed id, address indexed author, string text);

    function setUp() public {
        token = new TestEQTY();
        book = new EQTYGuestbook(address(token), FEE);
        vm.prank(alice);
        token.faucet();
    }

    function _post(address who, string memory text) internal returns (uint256) {
        vm.startPrank(who);
        token.approve(address(book), FEE);
        uint256 id = book.post(text);
        vm.stopPrank();
        return id;
    }

    // --- happy path ---

    function test_post_burnsFeeAndStoresMessage() public {
        uint256 supplyBefore = token.totalSupply();
        vm.warp(1_800_000_000);

        vm.startPrank(alice);
        token.approve(address(book), FEE);
        vm.expectEmit(true, true, false, true, address(book));
        emit Posted(0, alice, "Hallo EQTY!");
        uint256 id = book.post("Hallo EQTY!");
        vm.stopPrank();

        assertEq(id, 0);
        assertEq(book.count(), 1);
        (address author, uint64 ts, string memory text) = book.messageAt(0);
        assertEq(author, alice);
        assertEq(ts, 1_800_000_000);
        assertEq(text, "Hallo EQTY!");
        assertEq(token.balanceOf(alice), 900 ether);
        assertEq(token.totalSupply(), supplyBefore - FEE);
        assertEq(token.allowance(alice, address(book)), 0, "exact approval is fully used");
        assertEq(token.balanceOf(address(book)), 0, "guestbook never holds tokens");
    }

    function test_post_idsIncrement() public {
        _post(alice, "een");
        _post(alice, "twee");
        assertEq(book.count(), 2);
        (,, string memory t) = book.messageAt(1);
        assertEq(t, "twee");
    }

    function test_post_unicodeAllowed() public {
        _post(alice, unicode"Café ☕ – geweldig 🚀");
        (,, string memory t) = book.messageAt(0);
        assertEq(t, unicode"Café ☕ – geweldig 🚀");
    }

    function test_post_maxLength() public {
        _post(alice, string(_repeat("a", 560)));
        assertEq(book.count(), 1);
    }

    function test_zeroFee_noApprovalNeeded() public {
        EQTYGuestbook free = new EQTYGuestbook(address(token), 0);
        vm.prank(bob);
        free.post("gratis");
        assertEq(free.count(), 1);
    }

    // --- payment failures ---

    function test_revert_withoutApproval() public {
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(TestEQTY.ERC20InsufficientAllowance.selector, address(book), 0, FEE));
        book.post("geen approve");
        assertEq(book.count(), 0);
    }

    function test_revert_insufficientBalance() public {
        vm.startPrank(bob); // bob has no tokens
        token.approve(address(book), FEE);
        vm.expectRevert(abi.encodeWithSelector(TestEQTY.ERC20InsufficientBalance.selector, bob, 0, FEE));
        book.post("geen saldo");
        vm.stopPrank();
        assertEq(book.count(), 0);
    }

    function test_revert_secondPostNeedsNewApproval() public {
        _post(alice, "eerste");
        vm.prank(alice);
        vm.expectRevert();
        book.post("tweede zonder approve");
    }

    function test_cannotSendEth() public {
        vm.deal(alice, 1 ether);
        vm.startPrank(alice);
        token.approve(address(book), FEE);
        (bool ok,) = address(book).call{value: 1 wei}(abi.encodeCall(EQTYGuestbook.post, ("met eth")));
        vm.stopPrank();
        assertFalse(ok);
        (bool ok2,) = address(book).call{value: 1 wei}("");
        assertFalse(ok2);
        assertEq(address(book).balance, 0);
    }

    // --- content rules ---

    function test_revert_empty() public {
        vm.startPrank(alice);
        token.approve(address(book), FEE);
        vm.expectRevert(EQTYGuestbook.EmptyMessage.selector);
        book.post("");
        vm.stopPrank();
    }

    function test_revert_tooLong() public {
        vm.startPrank(alice);
        token.approve(address(book), FEE);
        vm.expectRevert(EQTYGuestbook.MessageTooLong.selector);
        book.post(string(_repeat("a", 561)));
        vm.stopPrank();
    }

    function test_revert_links() public {
        string[8] memory bad = [
            string("kijk op https://scam.xyz"),
            "HTTP is bad",
            "ga naar www.voorbeeld.nl",
            "WwW.Test.com",
            "ipfs://abc",
            "x://",
            "eindigt op http",
            "hTtPs"
        ];
        vm.startPrank(alice);
        token.approve(address(book), FEE);
        for (uint256 i; i < bad.length; ++i) {
            vm.expectRevert(EQTYGuestbook.LinksNotAllowed.selector);
            book.post(bad[i]);
        }
        vm.stopPrank();
    }

    function test_allowed_lookalikes() public {
        // Not links: single slash, "ww." etc.
        _post(alice, "1/2 of www en ww.x en ht tp: ok");
        assertEq(book.count(), 1);
    }

    function test_revert_controlChars() public {
        vm.startPrank(alice);
        token.approve(address(book), FEE);
        vm.expectRevert(EQTYGuestbook.InvalidCharacter.selector);
        book.post("regel1\nregel2");
        vm.expectRevert(EQTYGuestbook.InvalidCharacter.selector);
        book.post(string(abi.encodePacked("tab", bytes1(0x09))));
        vm.expectRevert(EQTYGuestbook.InvalidCharacter.selector);
        book.post(string(abi.encodePacked("del", bytes1(0x7f))));
        vm.stopPrank();
    }

    function test_constructor_rejectsZeroToken() public {
        vm.expectRevert(EQTYGuestbook.ZeroAddress.selector);
        new EQTYGuestbook(address(0), FEE);
    }

    function test_messageAt_outOfRangeReverts() public {
        vm.expectRevert();
        book.messageAt(0);
    }

    function test_immutableConfig() public view {
        assertEq(address(book.token()), address(token));
        assertEq(book.fee(), FEE);
        assertEq(book.MAX_BYTES(), 560);
    }

    // --- fuzz ---

    function testFuzz_lengthRule(uint16 len) public {
        len = uint16(bound(len, 1, 700));
        vm.startPrank(alice);
        token.approve(address(book), FEE);
        if (len > 560) vm.expectRevert(EQTYGuestbook.MessageTooLong.selector);
        book.post(string(_repeat("b", len)));
        vm.stopPrank();
    }

    function _repeat(bytes1 c, uint256 n) internal pure returns (bytes memory b) {
        b = new bytes(n);
        for (uint256 i; i < n; ++i) b[i] = c;
    }
}
