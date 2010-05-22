$(function () {
    $("a.chooser").fancybox();
    $("#images a").live("click", function () {
        imageId = $(this).attr("id");
        selectedImg = $(this).children()[0];
        $.fancybox.close();
        $("input.chooser-input").val(imageId);
        $("div.img-chooser-wrap").html(selectedImg);
        if ($("a.chooser").text() == 'Add') {
            $("a.chooser").text('Change');
            $("a.chooser").after(' <a href="#" class="chooser-remove">Remove</a>');
        }
        return false;
    });
    $("a.chooser-remove").live("click", function () {
        $("input.chooser-input").val('');
        $("div.img-chooser-wrap").text('No image selected.');
        $(this).prev().text("Add");
        $(this).remove();
        return false;
    });
});