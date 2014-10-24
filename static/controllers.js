
var phonecatApp = angular.module('phonecatApp', ['angular.filter', 'ngSanitize']);

phonecatApp.config(function($interpolateProvider) {
    $interpolateProvider.startSymbol('[[');
    $interpolateProvider.endSymbol(']]');
});

phonecatApp.controller('FeedListCtrl', function ($scope, $http) {
  $http.get('/api/1/feeds').success(function(data) {
    console.log(data)
    $scope.feeds = data.feeds;
  });

  $scope.orderProp = 'category';
});


phonecatApp.controller('PostListCtrl', function ($scope, $http) {
  $scope._query = function (add_url) {
    url = '/api/1/posts';
    if (add_url) {
        url += add_url;
    }
    console.log(url);
    $http.get(url).success(function(data) {
      console.log(data);
      $scope.first_id = data.first_id;
      $scope.last_id = data.last_id;
      $scope.posts = data.posts;
      // TODO: do something if posts are empty.
    });
  };

  $scope.query = function (add_url) {
    var url = "/" + $scope.active_category;
    if (add_url) {
        url += add_url;
    }
    $scope._query(url);
  };

  $scope.read_newer = function(_id) {
    console.log('yo ' + _id);
    var add_url = "/newer/" + _id;
    $scope.query(add_url);
  };

  $scope.read_older = function(_id) {
    console.log('ho ' + _id);
    var add_url = "/older/" + _id;
    $scope.query(add_url);
  };

  $scope.switch_category = function(cat_name) {
    console.log(cat_name)
    $scope.active_category = cat_name;
    $scope.query();
  }

  $scope.start_crawl = function() {
    url = '/api/1/crawl';
    console.log(url);
    $http.get(url).success(function(data) {
      console.log(data);
    });
  }

  $http.get('/api/1/feeds').success(function(data) {
    console.log(data)
    $scope.feeds = data.feeds;
  });

  $scope.active_category = 'all';
  $scope.query();
  //$scope.orderProp = '_id';
});


// AngularJS only works within same controller...
// references
// http://qiita.com/naoiwata/items/61dd023355c7759a68ac
