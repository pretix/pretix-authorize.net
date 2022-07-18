/*global $, gettext */
'use strict';

var pretixauthorizenet = {
    authorizenet: null,
    continue_button: null,

    load: function () {
        if (pretixauthorizenet.authorizenet === null) {
            pretixauthorizenet.continue_button = $('.checkout-button-row').closest("form").find(".checkout-button-row .btn-primary");
            var $cont = $('<div id="authorizenet-button-container">');
            $cont.hide()
            $cont.append(
                $('<button>')
                    .addClass('AcceptUI')
                    .addClass('btn btn-primary btn-lg btn-block')
                    .text(gettext('Pay'))
                    .attr('data-billingAddressOptions', '{"show":false, "required":false}')
                    .attr('data-apiLoginID', $("#authorizenet_login_id").text())
                    .attr('data-clientKey', $("#authorizenet_client_key").text())
                    .attr('data-acceptUIFormBtnTxt', gettext('Pay'))
                    .attr('data-acceptUIFormHeaderTxt', gettext('Card Information'))
                    .attr('data-responseHandler', 'pretixAuthorizeNetResponse')
            )
            pretixauthorizenet.continue_button.closest('div').append($cont);
        }

        pretixauthorizenet.continue_button.prop("disabled", true);

        let sdk_url = $("#authorizenet_sdkurl").text();

        let sdkscript = document.createElement('script');
        let ready = false;
        let head = document.getElementsByTagName("head")[0];
        sdkscript.setAttribute('src', sdk_url);
        sdkscript.setAttribute('charset', 'utf-8');
        document.head.appendChild(sdkscript);

        sdkscript.onload = sdkscript.onreadystatechange = function () {
            if (!ready && (!this.readyState || this.readyState === "loaded" || this.readyState === "complete")) {
                ready = true;

                pretixauthorizenet.authorizenet = window.AcceptUI;

                // Handle memory leak in IE
                sdkscript.onload = sdkscript.onreadystatechange = null;
                if (head && sdkscript.parentNode) {
                    head.removeChild(sdkscript);
                }
            }
        };
    },

    ready: function () {
        $("input[name=payment][value^='authorizenet']").change(function () {
            pretixauthorizenet.renderButton($(this).val());
        });

        $("input[name=payment]").not("[value^='authorizenet']").change(function () {
            pretixauthorizenet.restore();
        });

        if ($("input[name=payment][value^='authorizenet']").is(':checked') || $(".payment-redo-form").length) {
            pretixauthorizenet.renderButton($("input[name=payment][value^='authorizenet']:checked").val());
        } else {
            pretixauthorizenet.restore();
        }
    },

    restore: function () {
        // if SDK has not been initialized, there shouldn't be anything to cleanup
        $('#authorizenet-button-container').hide()
        pretixauthorizenet.continue_button.prop("disabled", false).show();
    },

    renderButton: function (method) {
        $('#authorizenet-button-container').show()
        pretixauthorizenet.continue_button.hide();
    },

    handleResponse: function (response) {
        if (response.messages.resultCode === "Error") {
            for (msg of response.messages.message) {
                alert(
                    msg.code + ": " + msg.text
                );
            }
        } else {
            waitingDialog.show(gettext("Processing payment …"));
            document.getElementById("authorizenet-creditcard-datadescriptor").value = response.opaqueData.dataDescriptor;
            document.getElementById("authorizenet-creditcard-datavalue").value = response.opaqueData.dataValue;
            pretixauthorizenet.continue_button.closest("form").submit();
        }
    }
};

$(function () {
    pretixauthorizenet.load();

    function checkReady() {
        if (!pretixauthorizenet.authorizenet) {
            return window.setTimeout(checkReady, 500);
        }
        pretixauthorizenet.ready();
    }
    checkReady();
});

window.pretixAuthorizeNetResponse = function (response) {
    pretixauthorizenet.handleResponse(response)
}